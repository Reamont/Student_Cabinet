from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (Deadline, Discipline, Group, Lesson, Profile, RequestDraft,
                     StudentRequest, StudyBlock, ViewPreference, RequestHistory)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'], TIME_ZONE='Europe/Moscow',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = get_user_model().objects.create_user('experience-a')
        cls.b = get_user_model().objects.create_user('experience-b')
        cls.group = Group.objects.create(name='UX-DEMO')
        for user, name in [(cls.a, 'Алиса Демо'), (cls.b, 'Чужое ФИО')]:
            Profile.objects.create(user=user, group=cls.group, full_name=name,
                faculty='Вымышленный институт', program='Тест', student_number=f'UX-{user.pk}')
        cls.discipline = Discipline.objects.create(name='Демо-дисциплина')
        cls.day = date(2026, 11, 11)
        cls.cancelled = Lesson.objects.create(group=cls.group, discipline=cls.discipline,
            date=cls.day, start=time(9), end=time(10, 30), cancelled=True,
            teacher='Демо-преподаватель', room='Демо-101')
        cls.task = Deadline.objects.create(user=cls.a, discipline=cls.discipline,
            title='Моя учебная задача', due=timezone.make_aware(datetime(2026, 11, 11, 18)))
        cls.foreign_task = Deadline.objects.create(user=cls.b, discipline=cls.discipline,
            title='Чужая учебная задача', due=cls.task.due)
        cls.active = StudentRequest.objects.create(user=cls.a, kind='application', text='Моя активная заявка', status='sent')
        cls.finished = StudentRequest.objects.create(user=cls.a, kind='application', text='Моя готовая заявка', status='ready')
        cls.draft = RequestDraft.objects.create(user=cls.a, kind='application', text='Мой черновик')
        StudentRequest.objects.create(user=cls.b, kind='application', text='Чужая активная заявка')
        RequestDraft.objects.create(user=cls.b, kind='application', text='Чужой черновик')

    def setUp(self):
        clock = patch('django.utils.timezone.now', return_value=timezone.make_aware(datetime(2026, 11, 8, 8)))
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_login(self.a)

    def save_view(self, **data):
        return self.client.post(reverse('preference_save'), data, HTTP_ACCEPT='application/json')

    def remove_block(self):
        block = StudyBlock.objects.create(user=self.a, lesson=self.cancelled, deadline=self.task,
            date=self.day, start=time(9), end=time(10, 30))
        self.client.post(reverse('plan_remove', args=[block.pk]))
        return block

    def test_new_destinations_require_login_and_tasks_are_private(self):
        guest = Client()
        for name in ['study', 'tasks', 'more']:
            self.assertEqual(guest.get(reverse(name)).status_code, 302)
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, self.foreign_task.title)
        self.assertContains(self.client.get(reverse('tasks')), self.task.title)
        self.assertContains(self.client.get(reverse('study')), reverse('semester'))

    def test_about_is_public_separate_page_without_profile_data(self):
        for client in [Client(), self.client]:
            response = client.get(reverse('about'))
            self.assertContains(response, '<h1>О проекте и данных</h1>', html=True)
            self.assertContains(response, 'Не является официальным сервисом вуза.')
            self.assertNotContains(response, 'Студенческий билет')
            self.assertNotContains(response, 'Чужое ФИО')
        self.assertContains(self.client.get(reverse('profile')), 'href="/about/"')
        self.assertNotContains(self.client.get(reverse('profile')), '/profile/#about')

    def test_five_navigation_destinations_and_avatar(self):
        response = self.client.get(reverse('dashboard'))
        for url in ['/study/', '/more/', '/schedule/', '/requests/']:
            self.assertContains(response, f'href="{url}"')
        self.assertContains(response, 'aria-label="Открыть профиль"')

    def test_request_tabs_partition_data_and_counts(self):
        active = self.client.get(reverse('requests'))
        self.assertEqual(list(active.context['student_requests']), [self.active])
        self.assertNotContains(active, 'Мой черновик')
        history = self.client.get(reverse('requests'), {'tab': 'history'})
        self.assertEqual(list(history.context['student_requests']), [self.finished])
        drafts = self.client.get(reverse('requests'), {'tab': 'drafts'})
        self.assertContains(drafts, self.draft.text)
        for response in [active, history, drafts]:
            self.assertNotContains(response, 'Чужая активная заявка')
            self.assertNotContains(response, 'Чужой черновик')

    def test_clarification_direct_action_and_finished_repeat(self):
        self.active.status = 'clarify'
        self.active.save()
        response = self.client.get(reverse('requests'))
        self.assertContains(response, reverse('request_detail', args=[self.active.pk]) + '#clarification')
        self.assertNotContains(self.client.get(reverse('request_detail', args=[self.active.pk])), 'Повторить заявку')
        self.assertContains(self.client.get(reverse('request_detail', args=[self.finished.pk])), 'Повторить заявку')
        self.assertEqual(self.client.get(reverse('dashboard')).context['next_action']['button'], 'Ответить на уточнение')

    def test_next_action_is_own_nearest_deadline_then_overdue(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['next_action']['title'], self.task.title)
        self.task.due -= timedelta(days=5)
        self.task.save()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['next_action']['title'], self.task.title)
        self.assertIn('Срок прошёл', response.context['next_action']['reason'])
        self.assertNotContains(response, self.foreign_task.title)

    def test_preference_get_is_read_only_and_post_restores_view(self):
        self.client.get(reverse('schedule'), {'mode': 'week'})
        self.assertFalse(ViewPreference.objects.exists())
        self.assertEqual(self.save_view(schedule_mode='week', requests_tab='history').json(), {'saved': True})
        self.assertEqual(self.client.get(reverse('schedule')).context['mode'], 'week')
        self.assertEqual(self.client.get(reverse('requests')).context['selected_tab'], 'history')
        self.assertEqual(self.client.get(reverse('schedule'), {'mode': 'today'}).context['mode'], 'today')
        self.client.logout()
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse('schedule')).context['mode'], 'week')

    def test_preferences_cannot_change_another_account_and_do_not_leak(self):
        self.save_view(schedule_mode='week', user_id=self.b.pk, user=self.b.pk)
        self.assertFalse(ViewPreference.objects.filter(user=self.b).exists())
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('schedule')).context['mode'], 'today')
        self.save_view(schedule_mode='today')
        self.assertEqual(ViewPreference.objects.get(user=self.a).values['schedule_mode'], 'week')

    def test_invalid_preference_is_rejected_atomically_and_unknown_fields_ignored(self):
        self.save_view(schedule_mode='week')
        self.assertEqual(self.save_view(schedule_mode='today', requests_tab='bad').status_code, 422)
        self.assertEqual(self.save_view(password='secret').status_code, 422)
        self.assertEqual(ViewPreference.objects.get(user=self.a).values, {'schedule_mode': 'week'})
        self.assertEqual(self.save_view(ideas_sort='popular').status_code, 200)
        self.assertEqual(ViewPreference.objects.get(user=self.a).values,
                         {'schedule_mode': 'week', 'ideas_sort': 'popular'})

    def test_remembered_filters_can_be_explicitly_cleared(self):
        self.save_view(notifications_kind='request', notifications_unread='1', semester_kind='tasks',
                       ideas_status='planned', ideas_sort='popular')
        response = self.client.get(reverse('notifications'), {'kind': '', 'unread': '0'})
        self.assertEqual(response.context['view_memory'], {'notifications_kind': '', 'notifications_unread': '0'})
        self.assertEqual(self.client.get(reverse('semester')).context['selected_kind'], 'tasks')
        self.assertEqual(self.client.get(reverse('semester'), {'kind': ''}).context['selected_kind'], '')
        self.assertTrue(self.client.get(reverse('ideas')).context['popular'])

    def test_preferences_require_post_login_and_csrf_and_safe_next(self):
        self.assertEqual(self.client.get(reverse('preference_save')).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(reverse('preference_save'), {'schedule_mode': 'week'}).status_code, 403)
        self.assertEqual(Client().post(reverse('preference_save'), {'schedule_mode': 'week'}).status_code, 302)
        response = self.client.post(reverse('preference_save'), {'schedule_mode': 'week', 'next': 'https://evil.invalid/'})
        self.assertRedirects(response, reverse('dashboard'))
        response = self.client.post(reverse('preference_save'), {'schedule_mode': 'week', 'next': '/schedule/'})
        self.assertRedirects(response, reverse('schedule'))

    def test_tasks_toggle_returns_to_task_and_remains_private(self):
        url = reverse('deadline_toggle', args=[self.task.pk])
        self.assertRedirects(self.client.post(url, {'done': '1', 'return_to': 'tasks'}),
                             reverse('tasks') + f'#deadline-{self.task.pk}')
        self.assertEqual(self.client.post(reverse('deadline_toggle', args=[self.foreign_task.pk]), {'done': '1'}).status_code, 404)

    def test_undo_restores_removed_block_once_without_completing_task(self):
        self.remove_block()
        self.assertFalse(StudyBlock.objects.exists())
        response = self.client.get(reverse('plan_b'), {'date': self.day.isoformat()})
        self.assertContains(response, 'Вернуть задачу')
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('plan_restore')).status_code, 302)
        self.assertEqual(StudyBlock.objects.filter(user=self.a, deadline=self.task).count(), 1)
        self.task.refresh_from_db()
        self.assertFalse(self.task.done)
        self.assertNotIn('study_undo', self.client.session)

    def test_undo_expires_and_cannot_be_forged_by_post(self):
        self.remove_block()
        session = self.client.session
        session['study_undo'] = {**session['study_undo'], 'expires': timezone.now().timestamp() - 1}
        session.save()
        self.client.post(reverse('plan_restore'), {'deadline': self.task.pk, 'expires': 9999999999})
        self.assertFalse(StudyBlock.objects.exists())

    def test_undo_rejects_foreign_session_owner_and_task(self):
        self.remove_block()
        snapshot = self.client.session['study_undo']
        self.client.force_login(self.b)
        self.client.post(reverse('plan_restore'))
        self.assertFalse(StudyBlock.objects.exists())
        self.client.force_login(self.a)
        session = self.client.session
        session['study_undo'] = {**snapshot, 'deadline': self.foreign_task.pk}
        session.save()
        self.client.post(reverse('plan_restore'))
        self.assertFalse(StudyBlock.objects.exists())

    def test_undo_revalidates_changed_schedule_done_task_and_conflict(self):
        self.remove_block()
        self.cancelled.cancelled = False
        self.cancelled.save()
        self.assertEqual(self.client.post(reverse('plan_restore')).status_code, 422)
        self.assertFalse(StudyBlock.objects.exists())
        self.cancelled.cancelled = True
        self.cancelled.save()
        self.task.done = True
        self.task.save()
        self.assertEqual(self.client.post(reverse('plan_restore')).status_code, 422)
        self.task.done = False
        self.task.save()
        other = Deadline.objects.create(user=self.a, discipline=self.discipline, title='Другая задача', due=self.task.due)
        StudyBlock.objects.create(user=self.a, lesson=self.cancelled, deadline=other,
            date=self.day, start=time(9), end=time(10, 30))
        self.assertEqual(self.client.post(reverse('plan_restore')).status_code, 422)
        self.assertEqual(StudyBlock.objects.get().deadline_id, other.pk)

    def test_undo_requires_csrf_and_post(self):
        self.assertEqual(self.client.get(reverse('plan_restore')).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        self.assertEqual(csrf_client.post(reverse('plan_restore')).status_code, 403)

    def test_invalid_clarification_retains_latest_employee_question(self):
        self.active.status = 'clarify'
        self.active.save()
        RequestHistory.objects.create(request=self.active, status='clarify', comment='Уточните вымышленную учебную цель.')
        response = self.client.post(reverse('request_clarify', args=[self.active.pk]), {'text': 'Я'})
        self.assertContains(response, 'Уточните вымышленную учебную цель.', status_code=422)
        self.assertEqual(response.context['clarification_form']['text'].value(), 'Я')
        self.active.refresh_from_db()
        self.assertEqual(self.active.status, 'clarify')
