from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from .models import Deadline, Discipline, Group, Notification, Profile, RequestDraft
from .services import sync_task_notification
from .task_forms import TaskForm


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
)
@skipUnlessDBFeature('has_select_for_update')
class ConcurrentUpdateTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('concurrency-demo')
        group = Group.objects.create(name='CONCURRENCY-DEMO')
        Profile.objects.create(user=self.user, group=group, full_name='Демо студент',
                               faculty='Демо', program='Демо', student_number='CONCURRENCY-DEMO')
        self.discipline = Discipline.objects.create(name='Демо дисциплина')
        self.task = Deadline.objects.create(user=self.user, discipline=self.discipline,
                                            title='Демо задача', due=timezone.now() + timedelta(days=1))
        self.first = Client()
        self.second = Client()
        self.first.force_login(self.user)
        self.second.force_login(self.user)

    def post(self, client, url, data, **kwargs):
        try:
            return client.post(url, data, **kwargs)
        finally:
            connections.close_all()

    def test_edit_and_completion_both_survive_parallel_requests(self):
        sync_task_notification(self.task)
        edit_url = reverse('task_edit', args=[self.task.pk])
        token = self.first.get(edit_url).context['form']['token'].value()
        ready, release, toggling, toggled = Event(), Event(), Event(), Event()
        original = TaskForm.save

        def pause_edit(form, *args, **kwargs):
            ready.set()
            if not release.wait(10):
                raise AssertionError('Edit was not released')
            return original(form, *args, **kwargs)

        def toggle():
            toggling.set()
            try:
                return self.post(self.second, reverse('deadline_toggle', args=[self.task.pk]), {'done': '1'})
            finally:
                toggled.set()

        with patch.object(TaskForm, 'save', pause_edit), ThreadPoolExecutor(max_workers=2) as pool:
            edit = pool.submit(self.post, self.first, edit_url, {
                'title': 'Новое название', 'discipline': self.discipline.pk,
                'due': '2026-11-26T18:00', 'token': token})
            try:
                self.assertTrue(ready.wait(10))
                completion = pool.submit(toggle)
                self.assertTrue(toggling.wait(10))
                # Completion must wait for the task row held by editing.
                self.assertFalse(toggled.wait(0.5))
            finally:
                release.set()
            self.assertEqual(edit.result(timeout=10).status_code, 302)
            self.assertEqual(completion.result(timeout=10).status_code, 302)
        self.task.refresh_from_db()
        self.assertTrue(self.task.done)
        self.assertEqual(self.task.title, 'Новое название')
        self.assertIn('Задача выполнена.', Notification.objects.get(related_deadline=self.task).body)

    def test_two_tabs_saving_one_version_cannot_silently_overwrite(self):
        form = self.first.get(reverse('request_new')).context['form']
        data = {'token': form['token'].value(), 'kind': 'application', 'text': 'Исходный текст'}
        url = reverse('draft_save')
        saved = self.first.post(url, data, HTTP_ACCEPT='application/json')
        data['draft_version'] = saved.json()['draft_version']
        start = Barrier(2)

        def save(client, text):
            start.wait(timeout=10)
            return text, self.post(client, url, {**data, 'text': text}, HTTP_ACCEPT='application/json')

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, self.first, 'Текст первой вкладки'),
                       pool.submit(save, self.second, 'Текст второй вкладки')]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(response.status_code for _, response in results), [200, 409])
        winner = next(text for text, response in results if response.status_code == 200)
        self.assertEqual(RequestDraft.objects.get(user=self.user).text, winner)
        conflict = next(response for _, response in results if response.status_code == 409)
        self.assertIn('conflict_url', conflict.json())
