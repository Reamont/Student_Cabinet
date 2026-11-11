from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
import io
import os
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Deadline, DemoTaskSeed, Discipline, Group, Notification, Profile, RequestDraft, TaskSubmission


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class RegressionTests(TestCase):
    def setUp(self):
        self.password = 'Test-only-password-827462'
        self.a = get_user_model().objects.create_user('reg-a', password=self.password)
        self.b = get_user_model().objects.create_user('reg-b', password=self.password)
        group = Group.objects.create(name='REG-DEMO')
        for u in [self.a, self.b]:
            Profile.objects.create(user=u,group=group,full_name='Демо студент',faculty='Демо',program='Демо',student_number=f'REG-{u.pk}')
        self.discipline = Discipline.objects.create(name='Демо предмет')
        self.task = Deadline.objects.create(user=self.a,discipline=self.discipline,title='Исходная задача',due=timezone.now())
        self.client.force_login(self.a)

    def payload(self):
        r = self.client.get(reverse('task_new'))
        return {'title':'Новая личная задача','discipline':self.discipline.pk,'due':'2026-11-26T18:00',
                'token':r.context['form']['token'].value()}

    def test_create_replay_and_replay_after_deletion(self):
        data=self.payload()
        self.client.post(reverse('task_new'),data)
        self.client.post(reverse('task_new'),data)
        task=Deadline.objects.get(title=data['title'])
        self.assertEqual(Notification.objects.filter(related_deadline=task).count(),1)
        self.client.post(reverse('task_delete',args=[task.pk]))
        self.client.post(reverse('task_new'),data)
        self.assertFalse(Deadline.objects.filter(title=data['title']).exists())
        self.assertEqual(TaskSubmission.objects.count(),1)

    def test_update_and_delete_keep_notification_consistent(self):
        data=self.payload();self.client.post(reverse('task_new'),data)
        task=Deadline.objects.get(title=data['title'])
        note=Notification.objects.get(related_deadline=task)
        note.read_at=timezone.now();note.save()
        edit=self.client.get(reverse('task_edit',args=[task.pk]))
        data.update(title='Изменённая задача',due='2026-11-27T20:30',token=edit.context['form']['token'].value())
        self.assertEqual(self.client.post(reverse('task_edit',args=[task.pk]),data).status_code,302)
        note.refresh_from_db()
        self.assertIn(data['title'],note.title)
        self.assertIn('27.11.2026 20:30',note.body)
        self.assertIsNone(note.read_at)
        self.assertContains(self.client.get(reverse('notification_detail',args=[note.pk])),f'#deadline-{task.pk}')
        self.client.post(reverse('task_delete',args=[task.pk]))
        self.assertFalse(Notification.objects.filter(pk=note.pk).exists())

    def test_tokens_validation_owner_and_csrf(self):
        data=self.payload();self.client.force_login(self.b)
        self.assertEqual(self.client.post(reverse('task_new'),data).status_code,422)
        for route in ['task_edit','task_delete']:
            self.assertEqual(self.client.get(reverse(route,args=[self.task.pk])).status_code,404)
            self.assertEqual(self.client.post(reverse(route,args=[self.task.pk]),data).status_code,404)
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(reverse('task_new'),{**data,'due':'bad'}).status_code,422)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.a)
        self.assertEqual(csrf.post(reverse('task_new'),data).status_code,403)

    def test_deleted_draft_rejects_old_autosave(self):
        from .forms import RequestForm
        data={'token':RequestForm(user=self.a).fields['token'].initial,'kind':'application','text':'Демо текст обращения'}
        self.client.post(reverse('draft_save'),data,HTTP_ACCEPT='application/json')
        draft=RequestDraft.objects.get(user=self.a)
        self.client.post(reverse('draft_delete',args=[draft.idempotency_key]))
        self.assertEqual(self.client.post(reverse('draft_save'),data,HTTP_ACCEPT='application/json').status_code,409)
        self.assertFalse(RequestDraft.objects.filter(user=self.a).exists())
        data['token'] = RequestForm(user=self.a).fields['token'].initial
        self.assertEqual(self.client.post(reverse('draft_save'),data,HTTP_ACCEPT='application/json').status_code,200)

    def test_seed_preserves_edited_and_deleted_demo_tasks(self):
        env={'DEMO_STUDENT_PASSWORD':self.password,'DEMO_SECOND_PASSWORD':self.password,'DEMO_STAFF_PASSWORD':self.password}
        with patch.dict(os.environ,env):
            call_command('seed_demo',stdout=io.StringIO())
            user=get_user_model().objects.get(username='alisa')
            marker=DemoTaskSeed.objects.get(user=user,key='demo-task-0')
            task=marker.task;task.title='Своё название';task.save()
            removed=DemoTaskSeed.objects.get(user=user,key='demo-task-1').task
            removed.delete()
            before=Deadline.objects.filter(user=user).count()
            call_command('seed_demo',stdout=io.StringIO())
            self.assertEqual(Deadline.objects.filter(user=user).count(),before)
            task.refresh_from_db();self.assertEqual(task.title,'Своё название')
            self.assertIsNone(DemoTaskSeed.objects.get(user=user,key='demo-task-1').task_id)
            self.assertFalse(Deadline.objects.filter(user=user,title='Отправить проектную работу').exists())

    def test_retired_feature_has_no_model_routes_or_ui(self):
        with self.assertRaises(LookupError):apps.get_model('portal','StudyBlock')
        for path in ['/plan-b/','/plan-b/restore/','/plan-b/blocks/1/remove/','/plan-b/lessons/1/choose/']:
            self.assertEqual(self.client.get(path).status_code,404)
            self.assertEqual(self.client.post(path).status_code,404)
        for name in ['dashboard','schedule','semester','about','tasks','student_help']:
            response=self.client.get(reverse(name))
            self.assertNotContains(response,'План Б')
            self.assertNotContains(response,'/plan-b/')

    def test_successful_logins_never_consume_failure_limit(self):
        self.client.logout()
        for _ in range(45):
            c=Client()
            self.assertEqual(c.post(reverse('login'),{'username':self.a.username,'password':self.password}).status_code,302)

    def test_success_resets_account_failures(self):
        self.client.logout()
        for _ in range(9):self.client.post(reverse('login'),{'username':self.a.username,'password':'bad'})
        self.assertEqual(self.client.post(reverse('login'),{'username':self.a.username,'password':self.password}).status_code,302)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('login'),{'username':self.a.username,'password':'bad'}).status_code,200)

    @override_settings(LOGIN_RATE_LIMIT_AT_PROXY=True)
    def test_shared_proxy_and_spoofed_forwarding_do_not_merge_accounts(self):
        self.client.logout()
        for _ in range(10):
            self.client.post(reverse('login'),{'username':self.a.username,'password':'bad'},REMOTE_ADDR='172.18.0.1')
        self.assertEqual(self.client.post(reverse('login'),{'username':self.a.username,'password':self.password},HTTP_X_FORWARDED_FOR='203.0.113.3').status_code,429)
        self.assertEqual(self.client.post(reverse('login'),{'username':self.b.username,'password':self.password},REMOTE_ADDR='172.18.0.1').status_code,302)

    def test_nginx_and_compose_keep_trust_boundary(self):
        root=Path(__file__).resolve().parent.parent
        nginx=(root/'deploy/nginx.conf').read_text()
        compose=(root/'deploy/compose.yaml').read_text()
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;',nginx)
        self.assertIn('proxy_set_header X-Forwarded-Proto https;',nginx)
        self.assertIn('LOGIN_RATE_LIMIT_AT_PROXY: "1"',compose)
        self.assertIn('127.0.0.1:8000:8000',compose)




    def test_changed_task_replay_reports_conflict_and_keeps_input(self):
        data = self.payload()
        self.client.post(reverse('task_new'), data)
        for changes in ({'title': 'Другое название'}, {'due': '2026-12-01T12:00'}):
            response = self.client.post(reverse('task_new'), {**data, **changes})
            self.assertEqual(response.status_code, 409)
            for field, value in changes.items():
                self.assertEqual(response.context['form'][field].value(), value)
        self.assertEqual(Deadline.objects.filter(title=data['title']).count(), 1)

    def test_unchanged_task_edit_preserves_read_notification(self):
        data = self.payload()
        self.client.post(reverse('task_new'), data)
        task = Deadline.objects.get(title=data['title'])
        note = Notification.objects.get(related_deadline=task)
        note.read_at = timezone.now()
        note.save()
        before = (note.read_at, note.created_at)
        edit = self.client.get(reverse('task_edit', args=[task.pk]))
        data['token'] = edit.context['form']['token'].value()
        self.assertEqual(self.client.post(reverse('task_edit', args=[task.pk]), data).status_code, 302)
        note.refresh_from_db()
        self.assertEqual((note.read_at, note.created_at), before)

    @override_settings(LOGIN_RATE_LIMIT_AT_PROXY=True)
    def test_success_between_failure_counter_creation_and_lock(self):
        from django.test import RequestFactory
        from .middleware import failed_login, successful_login, login_keys
        from .models import LoginThrottle
        request = RequestFactory().post('/login/', {'username': self.a.username})
        original = LoginThrottle.objects.get_or_create

        def interleave(*args, **kwargs):
            result = original(*args, **kwargs)
            successful_login(sender=None, request=request, user=self.a)
            return result

        with patch.object(LoginThrottle.objects, 'get_or_create', side_effect=interleave):
            failed_login(sender=None, credentials={'username': self.a.username}, request=request)
        key, _ = login_keys(request, self.a.username)[0]
        self.assertEqual(LoginThrottle.objects.get(key=key).failures, 1)


class UpgradeRegressionTests(TransactionTestCase):
    def test_upgrade_preserves_tasks_and_links_notices_and_drops_retired_table(self):
        old = [('portal', '0006_viewpreference')]
        new = [('portal', '0008_preserve_demo_tasks')]
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        try:
            historical = executor.loader.project_state(old).apps
            User = historical.get_model('auth', 'User')
            Disc = historical.get_model('portal', 'Discipline')
            Task = historical.get_model('portal', 'Deadline')
            Note = historical.get_model('portal', 'Notification')
            user = User.objects.create(username='alisa')
            disc = Disc.objects.create(name='Демо миграция')
            task = Task.objects.create(user=user,discipline=disc,title='Отправить проектную работу',due=timezone.now())
            note = Note.objects.create(user=user,kind='deadline',title='Учебная задача: '+task.title,body='Старый срок')
            executor = MigrationExecutor(connection)
            executor.migrate(new)
            self.assertTrue(Deadline.objects.filter(pk=task.pk).exists())
            self.assertEqual(Notification.objects.get(pk=note.pk).related_deadline_id,task.pk)
            self.assertEqual(DemoTaskSeed.objects.get(user_id=user.pk,key='demo-task-0').task_id,task.pk)
            self.assertIsNone(DemoTaskSeed.objects.get(user_id=user.pk,key='demo-task-1').task_id)
            self.assertNotIn('portal_studyblock',connection.introspection.table_names())
        finally:
            MigrationExecutor(connection).migrate(new)
