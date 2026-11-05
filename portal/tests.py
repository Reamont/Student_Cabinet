"""Integration checks for user isolation, complete workflows and security boundaries.

Each test uses its own transaction/test database; no demo/student data is touched.
"""
import io
import os
from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import RequestForm
from .models import (
    Announcement, Deadline, Discipline, Group, LearningResult, Lesson,
    LoginThrottle, Notification, Profile, RequestHistory, StudentRequest,
)


@override_settings(
    # Django's in-process client uses HTTP/testserver; live production redirect
    # and Secure cookies are verified separately against Gunicorn behind proxy.
    SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['testserver'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class PortalIntegrationTests(TestCase):
    password = 'Test-only-password-4728'

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.alisa = User.objects.create_user('alice-test', password=cls.password)
        cls.boris = User.objects.create_user('boris-test', password=cls.password)
        cls.employee = User.objects.create_superuser('staff-test', password=cls.password)
        cls.staff_no_permission = User.objects.create_user('limited-staff', password=cls.password, is_staff=True)
        cls.group_a = Group.objects.create(name='TEST-A')
        cls.group_b = Group.objects.create(name='TEST-B')
        for user, group, name in [(cls.alisa, cls.group_a, 'Алиса Тестовая'), (cls.boris, cls.group_b, 'Борис Другой')]:
            Profile.objects.create(user=user, group=group, full_name=name, faculty='Тестовый факультет',
                                   program='Тестовое направление', year=2, student_number=f'TEST-{user.pk}')
        cls.discipline_a = Discipline.objects.create(name='Предмет только Алисы')
        cls.discipline_b = Discipline.objects.create(name='Предмет только Бориса')
        cls.request_a = StudentRequest.objects.create(user=cls.alisa, kind='study', text='Обращение только Алисы')
        cls.request_b = StudentRequest.objects.create(user=cls.boris, kind='application', text='Секретный вопрос Бориса')
        RequestHistory.objects.create(request=cls.request_b, status='sent', comment='Приватный комментарий Бориса')
        cls.announcement = Announcement.objects.create(title='Общее объявление', body='Открытие читального зала')
        cls.notification_a = Notification.objects.create(user=cls.alisa, kind='announcement', title='Общее объявление',
                                                         body='Открытие читального зала', announcement=cls.announcement)
        cls.notification_b = Notification.objects.create(user=cls.boris, kind='announcement', title='Общее объявление',
                                                         body='Открытие читального зала', announcement=cls.announcement)
        cls.private_notification = Notification.objects.create(user=cls.boris, kind='deadline',
                                                                title='Личный дедлайн Бориса', body='Приватные сведения')
        cls.deadline_b = Deadline.objects.create(user=cls.boris, discipline=cls.discipline_b,
                                                title='Задача Бориса', due=timezone.now() + timedelta(days=2))
        for user, discipline in [(cls.alisa, cls.discipline_a), (cls.boris, cls.discipline_b)]:
            Lesson.objects.create(group=user.profile.group, discipline=discipline, date=timezone.localdate(),
                                  start=time(10), end=time(11, 30), room='101', teacher='Тестовый преподаватель')

    def setUp(self):
        self.client.force_login(self.alisa)

    def request_payload(self, user=None, **overrides):
        payload = {
            'kind': 'study', 'destination': '', 'text': '',
            'token': RequestForm(user=user or self.alisa).fields['token'].initial,
        }
        payload.update(overrides)
        return payload

    def test_valid_and_invalid_login(self):
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': self.alisa.username, 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('login'), {'username': self.alisa.username, 'password': self.password})
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.alisa.pk)

    def test_protected_pages_require_login(self):
        self.client.logout()
        for name in ['dashboard', 'schedule', 'grades', 'requests', 'request_new', 'notifications', 'profile']:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse('login')))
        response = self.client.post(reverse('request_submit'), self.request_payload())
        self.assertEqual(response.status_code, 302)

    def test_logout_revokes_access_and_requires_post(self):
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('logout')), reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 302)

    def test_safe_next_login_url_cannot_redirect_to_external_site(self):
        self.client.logout()
        response = self.client.post(reverse('login') + '?next=https://attacker.invalid/',
                                    {'username': self.alisa.username, 'password': self.password})
        self.assertRedirects(response, reverse('dashboard'))

    def test_student_data_cannot_be_selected_by_client_user_id(self):
        response = self.client.get(reverse('profile'), {'user_id': self.boris.pk})
        self.assertContains(response, 'Алиса Тестовая')
        self.assertNotContains(response, 'Борис Другой')
        response = self.client.get(reverse('requests'), {'user_id': self.boris.pk})
        self.assertContains(response, self.request_a.number)
        self.assertNotContains(response, self.request_b.number)

    def test_foreign_request_and_notification_ids_are_hidden(self):
        for name, pk in [('request_detail', self.request_b.pk), ('notification_detail', self.private_notification.pk)]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=[pk]))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, 'Приватные сведения', status_code=404)
        self.assertEqual(self.client.post(reverse('request_clarify', args=[self.request_b.pk]),
                                          {'text': 'Пытаюсь изменить чужую заявку'}).status_code, 404)
        self.assertEqual(self.client.post(reverse('notification_read', args=[self.notification_b.pk])).status_code, 404)
        self.request_b.refresh_from_db()
        self.notification_b.refresh_from_db()
        self.assertEqual(self.request_b.status, 'sent')
        self.assertIsNone(self.notification_b.read_at)

    def test_foreign_deadline_cannot_be_changed(self):
        response = self.client.post(reverse('deadline_toggle', args=[self.deadline_b.pk]), {'done': '1'})
        self.assertEqual(response.status_code, 404)
        self.deadline_b.refresh_from_db()
        self.assertFalse(self.deadline_b.done)

    def test_create_review_persist_and_reopen_request(self):
        payload = self.request_payload(kind='application', text='Прошу выдать индивидуальный учебный план.')
        before = StudentRequest.objects.count()
        response = self.client.post(reverse('request_review'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentRequest.objects.count(), before)
        self.assertContains(response, payload['text'])
        response = self.client.post(reverse('request_submit'), payload)
        item = StudentRequest.objects.get(text=payload['text'])
        self.assertRedirects(response, reverse('request_detail', args=[item.pk]))
        self.assertEqual(item.user_id, self.alisa.pk)
        self.assertEqual(item.status, 'sent')
        self.assertEqual(item.history.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.alisa, related_request=item).count(), 1)
        self.client.logout()
        self.client.login(username=self.alisa.username, password=self.password)
        self.assertContains(self.client.get(reverse('request_detail', args=[item.pk])), payload['text'])

    def test_all_three_request_kinds_work(self):
        for kind, destination, text in [('study', '', ''), ('destination', 'Демо-организация', ''),
                                        ('application', '', 'Прошу рассмотреть тестовое заявление.')]:
            with self.subTest(kind=kind):
                response = self.client.post(reverse('request_submit'), self.request_payload(
                    kind=kind, destination=destination, text=text))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(StudentRequest.objects.filter(user=self.alisa, kind=kind, destination=destination, text=text).exists())

    def test_invalid_request_preserves_text_and_creates_nothing(self):
        before = StudentRequest.objects.count()
        payload = self.request_payload(kind='destination', destination='', text='Сохрани этот текст')
        response = self.client.post(reverse('request_review'), payload)
        self.assertEqual(response.status_code, 422)
        self.assertIn('destination', response.context['form'].errors)
        self.assertEqual(response.context['form']['text'].value(), payload['text'])
        response = self.client.post(reverse('request_submit'), self.request_payload(kind='application', text='Коротко'))
        self.assertEqual(response.status_code, 422)
        self.assertIn('text', response.context['form'].errors)
        self.assertEqual(StudentRequest.objects.count(), before)

    def test_owner_role_and_status_injection_is_ignored(self):
        payload = self.request_payload(text='Проверка подмены владельца')
        payload.update(user_id=self.boris.pk, user=self.boris.pk, status='ready', role='staff', is_staff='1')
        response = self.client.post(reverse('request_submit'), payload)
        self.assertEqual(response.status_code, 302)
        item = StudentRequest.objects.get(text='Проверка подмены владельца')
        self.assertEqual(item.user_id, self.alisa.pk)
        self.assertEqual(item.status, 'sent')
        self.alisa.refresh_from_db()
        self.assertFalse(self.alisa.is_staff)

    def test_repeated_submit_is_idempotent_and_changed_replay_conflicts(self):
        payload = self.request_payload(text='Проверка повторной отправки')
        first = self.client.post(reverse('request_submit'), payload)
        second = self.client.post(reverse('request_submit'), payload)
        self.assertEqual(first.url, second.url)
        item = StudentRequest.objects.get(text=payload['text'])
        self.assertEqual(item.history.count(), 1)
        payload['text'] = 'Другой текст того же токена'
        self.assertEqual(self.client.post(reverse('request_submit'), payload).status_code, 409)
        self.assertFalse(StudentRequest.objects.filter(text=payload['text']).exists())

    def test_form_token_is_signed_owner_bound_and_expires(self):
        for token in ['forged-token', self.request_payload(self.boris)['token']]:
            with self.subTest(token_kind='invalid-or-other-owner'):
                response = self.client.post(reverse('request_submit'), self.request_payload(token=token))
                self.assertEqual(response.status_code, 422)
        payload = self.request_payload()
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 7200):
            self.assertEqual(self.client.post(reverse('request_submit'), payload).status_code, 422)

    def test_notification_read_is_per_user_and_get_has_no_side_effect(self):
        self.assertEqual(self.client.get(reverse('notification_detail', args=[self.notification_a.pk])).status_code, 200)
        self.notification_a.refresh_from_db()
        self.assertIsNone(self.notification_a.read_at)
        self.assertEqual(self.client.get(reverse('notification_read', args=[self.notification_a.pk])).status_code, 405)
        self.client.post(reverse('notification_read', args=[self.notification_a.pk]))
        self.notification_a.refresh_from_db()
        self.notification_b.refresh_from_db()
        self.assertIsNotNone(self.notification_a.read_at)
        self.assertIsNone(self.notification_b.read_at)
        self.assertEqual(self.client.get(reverse('notifications'), {'unread': '1'}).context['notifications'].count(), 0)

    def test_notification_filters_do_not_expose_other_student(self):
        own = Notification.objects.create(user=self.alisa, kind='schedule', title='Моя перемена', body='Кабинет 202')
        response = self.client.get(reverse('notifications'), {'kind': 'schedule'})
        self.assertEqual(list(response.context['notifications']), [own])
        response = self.client.get(reverse('notifications'), {'kind': 'deadline'})
        self.assertEqual(list(response.context['notifications']), [])

    def test_csrf_is_required_for_state_changes_and_login(self):
        browser = Client(enforce_csrf_checks=True)
        response = browser.post(reverse('login'), {'username': self.alisa.username, 'password': self.password})
        self.assertEqual(response.status_code, 403)
        browser.force_login(self.alisa)
        for name, args, payload in [
            ('request_submit', [], self.request_payload()),
            ('notification_read', [self.notification_a.pk], {}),
            ('deadline_toggle', [self.deadline_b.pk], {'done': '1'}),
            ('logout', [], {}),
        ]:
            with self.subTest(name=name):
                self.assertEqual(browser.post(reverse(name, args=args), payload).status_code, 403)
        browser.get(reverse('request_new'))
        payload = self.request_payload(text='Проверка валидного CSRF')
        payload['csrfmiddlewaretoken'] = browser.cookies['csrftoken'].value
        self.assertEqual(browser.post(reverse('request_submit'), payload).status_code, 302)

    def test_student_cannot_use_employee_status_interface(self):
        url = reverse('admin:portal_studentrequest_change', args=[self.request_a.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(url, {'status': 'ready', '_save': 'Сохранить'}).status_code, 302)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, 'sent')
        self.client.force_login(self.staff_no_permission)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'status': 'ready', '_save': 'Сохранить'}).status_code, 403)

    def test_employee_status_transitions_write_history_and_notification(self):
        self.client.force_login(self.employee)
        url = reverse('admin:portal_studentrequest_change', args=[self.request_a.pk])
        for status, comment in [('work', ''), ('clarify', 'Уточните место требования.'),
                                ('ready', 'Справка готова к получению.'), ('rejected', 'Причина учебного отказа.')]:
            with self.subTest(status=status):
                response = self.client.post(url, {'status': status, 'comment': comment, '_save': 'Сохранить'})
                self.assertEqual(response.status_code, 302)
                self.request_a.refresh_from_db()
                self.assertEqual(self.request_a.status, status)
                self.assertEqual(self.request_a.history.last().comment, comment)
                self.assertEqual(Notification.objects.filter(user=self.alisa, related_request=self.request_a).first().body,
                                 comment or 'Статус обращения обновлён. Откройте заявку, чтобы узнать подробности.')

    def test_employee_must_explain_clarification_or_rejection(self):
        self.client.force_login(self.employee)
        url = reverse('admin:portal_studentrequest_change', args=[self.request_a.pk])
        for status in ['clarify', 'rejected']:
            response = self.client.post(url, {'status': status, 'comment': '  ', '_save': 'Сохранить'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('comment', response.context['adminform'].form.errors)
            self.request_a.refresh_from_db()
            self.assertEqual(self.request_a.status, 'sent')

    def test_employee_cannot_change_owner_via_extra_fields(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('admin:portal_studentrequest_change', args=[self.request_a.pk]),
                                    {'status': 'work', 'user': self.boris.pk, 'kind': 'application',
                                     'text': 'Подмена текста', '_save': 'Сохранить'})
        self.assertEqual(response.status_code, 302)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.user_id, self.alisa.pk)
        self.assertEqual(self.request_a.kind, 'study')
        self.assertEqual(self.request_a.text, 'Обращение только Алисы')

    def test_student_can_reply_only_to_own_clarification(self):
        self.request_a.status = 'clarify'
        self.request_a.save(update_fields=['status'])
        url = reverse('request_clarify', args=[self.request_a.pk])
        self.assertEqual(self.client.post(url, {'text': 'Да'}).status_code, 422)
        response = self.client.post(url, {'text': 'Справка нужна в тестовую библиотеку.', 'status': 'ready'})
        self.assertEqual(response.status_code, 302)
        self.request_a.refresh_from_db()
        self.assertEqual(self.request_a.status, 'sent')
        self.assertIn('Справка нужна', self.request_a.history.last().comment)

    def test_schedule_is_group_scoped_and_navigation_is_dynamic(self):
        response = self.client.get(reverse('schedule'))
        self.assertContains(response, self.discipline_a.name)
        self.assertNotContains(response, self.discipline_b.name)
        self.assertEqual(response.context['selected_date'], timezone.localdate())
        week = self.client.get(reverse('schedule'), {'mode': 'week'})
        self.assertEqual(len(week.context['days']), 7)
        future = timezone.localdate() + timedelta(days=31)
        response = self.client.get(reverse('schedule'), {'date': future.isoformat()})
        self.assertEqual(response.context['selected_date'], future)
        self.assertEqual(response.context['days'][0]['lessons'], [])
        invalid = self.client.get(reverse('schedule'), {'date': 'not-a-date'})
        self.assertEqual(invalid.context['selected_date'], timezone.localdate())

    def test_cancelled_and_changed_lessons_are_visible(self):
        Lesson.objects.create(group=self.group_a, discipline=self.discipline_a, date=timezone.localdate(),
                              start=time(14), end=time(15), room='204', old_room='101',
                              old_start=time(13), teacher='Преподаватель', change_note='Изменение аудитории и времени')
        Lesson.objects.create(group=self.group_a, discipline=self.discipline_a, date=timezone.localdate(),
                              start=time(16), end=time(17), room='305', cancelled=True,
                              teacher='Преподаватель', change_note='Отмена занятия')
        response = self.client.get(reverse('schedule'))
        self.assertContains(response, '204')
        self.assertContains(response, '101')
        self.assertContains(response, 'Изменение аудитории и времени')
        self.assertContains(response, 'Отмена занятия')

    def test_current_lesson_and_real_today_plan(self):
        # Compact dashboard cards must not truncate the underlying actionable plan.
        for i in range(6):
            Deadline.objects.create(user=self.alisa, discipline=self.discipline_a,
                                    title=f'Срочная задача {i}', due=timezone.now())
            StudentRequest.objects.create(user=self.alisa, kind='study', status='clarify')
        next_lesson = Lesson.objects.create(group=self.group_a, discipline=self.discipline_a,
                                            date=timezone.localdate(), start=time(12), end=time(13),
                                            room='202', teacher='Следующий преподаватель')
        fixed = timezone.make_aware(datetime.combine(timezone.localdate(), time(10, 30)))
        with patch('portal.views.timezone.localtime', return_value=fixed):
            response = self.client.get(reverse('dashboard'))
            schedule_response = self.client.get(reverse('schedule'))
        self.assertTrue(response.context['next_lesson'].is_current)
        marked_lessons = schedule_response.context['days'][0]['lessons']
        self.assertEqual([lesson.pk for lesson in marked_lessons if lesson.is_next], [next_lesson.pk])
        self.assertEqual(sum(lesson.is_current for lesson in marked_lessons), 1)
        self.assertTrue(any(self.discipline_a.name in p['title'] for p in response.context['plan']))
        self.assertFalse(any(self.discipline_b.name in p['title'] for p in response.context['plan']))
        self.assertEqual(sum(p['kind'] == 'Дедлайн' for p in response.context['plan']), 6)
        self.assertEqual(sum(p['kind'] == 'Заявка' for p in response.context['plan']), 6)

    def test_average_uses_only_numeric_grades_and_missing_is_not_debt(self):
        for state, grade in [('grade', 5), ('grade', 3), ('pass', None), ('pending', None), ('empty', None), ('debt', None)]:
            LearningResult.objects.create(user=self.alisa, discipline=self.discipline_a, state=state, grade=grade)
        LearningResult.objects.create(user=self.boris, discipline=self.discipline_b, state='grade', grade=2)
        response = self.client.get(reverse('grades'))
        self.assertEqual(response.context['average'], '4,00')
        self.assertEqual(len(response.context['results']), 6)
        self.assertNotContains(response, self.discipline_b.name)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual([r.state for r in dashboard.context['results_attention']], ['debt'])

    def test_user_text_is_escaped_and_private_responses_not_cached(self):
        # Client.force_login creates its own bare cookie; inspect a real HTTP login.
        self.client.logout()
        self.client.post(reverse('login'), {'username': self.alisa.username, 'password': self.password})
        attack = '<script>alert("xss")</script>'
        self.request_a.text = attack
        self.request_a.save(update_fields=['text'])
        response = self.client.get(reverse('request_detail', args=[self.request_a.pk]))
        self.assertNotContains(response, attack)
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertTrue(self.client.cookies['sessionid']['httponly'])
        self.assertEqual(self.client.cookies['sessionid']['samesite'], 'Lax')

    def test_throttle_limits_student_and_employee_login_and_expires(self):
        self.client.logout()
        for i in range(10):
            url = reverse('login') if i % 2 == 0 else reverse('admin:login')
            response = self.client.post(url, {'username': self.alisa.username, 'password': 'incorrect'})
            self.assertNotEqual(response.status_code, 429)
        response = self.client.post(reverse('login'), {'username': self.alisa.username, 'password': self.password})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '900')
        LoginThrottle.objects.update(started_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.client.post(reverse('login'), {'username': self.alisa.username, 'password': self.password}).status_code, 302)

    def test_throttle_by_address_prevents_username_rotation(self):
        self.client.logout()
        LoginThrottle.objects.all().delete()
        for i in range(40):
            self.assertEqual(self.client.post(reverse('login'), {'username': f'unknown-{i}', 'password': 'wrong'}).status_code, 200)
        response = self.client.post(reverse('admin:login'), {'username': 'yet-another', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)

    def test_invalid_numeric_grade_cannot_enter_database(self):
        for grade in [None, 1, 6]:
            with self.subTest(grade=grade), self.assertRaises(IntegrityError), transaction.atomic():
                LearningResult.objects.create(user=self.alisa, discipline=self.discipline_a, state='grade', grade=grade)

    def test_seed_requires_credentials_and_rolls_back_without_them(self):
        with patch.dict(os.environ, {'DEMO_STUDENT_PASSWORD': '', 'DEMO_SECOND_PASSWORD': '', 'DEMO_STAFF_PASSWORD': ''}):
            with self.assertRaises(CommandError):
                call_command('seed_demo', stdout=io.StringIO())
        self.assertFalse(get_user_model().objects.filter(username='alisa').exists())

    def test_seed_is_repeatable_and_preserves_requests_passwords_and_read_state(self):
        credentials = {
            'DEMO_STUDENT_PASSWORD': 'Test-demo-first-48327',
            'DEMO_SECOND_PASSWORD': 'Test-demo-second-72941',
            'DEMO_STAFF_PASSWORD': 'Test-demo-staff-63295',
        }
        with patch.dict(os.environ, credentials):
            call_command('seed_demo', stdout=io.StringIO())
        alisa = get_user_model().objects.get(username='alisa')
        curator = get_user_model().objects.get(username='curator')
        self.assertTrue(curator.is_staff)
        self.assertFalse(curator.is_superuser)
        self.assertTrue(curator.has_perm('portal.change_studentrequest'))
        self.assertFalse(curator.has_perm('auth.change_user'))
        saved_password = alisa.password
        custom_request = StudentRequest.objects.create(user=alisa, kind='application', text='Сохранить собственную заявку после seed')
        notification = Notification.objects.filter(user=alisa).first()
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
        model_classes = [get_user_model(), Profile, Lesson, LearningResult, Deadline, StudentRequest, RequestHistory, Notification]
        counts = {model: model.objects.count() for model in model_classes}
        with patch.dict(os.environ, {key: 'Different-test-password-19842' for key in credentials}):
            call_command('seed_demo', stdout=io.StringIO())
        self.assertEqual({model: model.objects.count() for model in model_classes}, counts)
        alisa.refresh_from_db()
        custom_request.refresh_from_db()
        notification.refresh_from_db()
        self.assertEqual(alisa.password, saved_password)
        self.assertTrue(alisa.check_password(credentials['DEMO_STUDENT_PASSWORD']))
        self.assertEqual(custom_request.text, 'Сохранить собственную заявку после seed')
        self.assertIsNotNone(notification.read_at)


    def test_future_deadline_is_not_hidden_by_overdue_tasks(self):
        now = timezone.now()
        overdue = [Deadline.objects.create(user=self.alisa, discipline=self.discipline_a,
                    title=f'Просроченная задача {i}', due=now-timedelta(days=i+1)) for i in range(5)]
        upcoming = Deadline.objects.create(user=self.alisa, discipline=self.discipline_a,
                    title='Завтрашняя задача', due=now+timedelta(days=1))
        Deadline.objects.create(user=self.alisa, discipline=self.discipline_a,
                    title='Уже выполнено', due=now+timedelta(hours=1), done=True)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual([d.pk for d in response.context['deadlines']], [upcoming.pk])
        plan_titles = [p['title'] for p in response.context['plan']]
        for task in overdue:
            self.assertIn(task.title, plan_titles)
        self.assertNotIn(self.deadline_b.title, plan_titles)

    def test_next_lesson_after_long_break_is_visible_and_group_scoped(self):
        Lesson.objects.filter(group=self.group_a).delete()
        future = timezone.localdate()+timedelta(days=30)
        Lesson.objects.create(group=self.group_a, discipline=self.discipline_a,
            date=future-timedelta(days=1), start=time(9), end=time(10),
            room='101', teacher='Отменённое', cancelled=True)
        expected = Lesson.objects.create(group=self.group_a, discipline=self.discipline_a,
            date=future, start=time(9), end=time(10), room='101', teacher='Следующее')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['next_lesson'].pk, expected.pk)
        self.assertFalse(response.context['next_lesson'].is_current)
        self.assertContains(response, f'?date={future.isoformat()}')

    @override_settings(LOGIN_RATE_LIMIT_AT_PROXY=True)
    def test_proxy_clients_do_not_share_app_address_limit(self):
        self.client.logout()
        for i in range(40):
            response = self.client.post(reverse('login'),
                {'username': f'unknown-{i}', 'password': 'wrong'},
                REMOTE_ADDR='172.18.0.1', HTTP_X_FORWARDED_FOR='192.0.2.1')
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('login'),
            {'username': self.alisa.username, 'password': self.password},
            REMOTE_ADDR='172.18.0.1', HTTP_X_FORWARDED_FOR='192.0.2.2')
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        response = self.client.post(reverse('login'),
            {'username': self.boris.username, 'password': self.password},
            REMOTE_ADDR='172.18.0.1', HTTP_X_FORWARDED_FOR='192.0.2.3')
        self.assertEqual(response.status_code, 302)

    @override_settings(LOGIN_RATE_LIMIT_AT_PROXY=True)
    def test_proxy_mode_keeps_account_limit_across_login_routes(self):
        self.client.logout()
        for i in range(10):
            url = reverse('login') if i % 2 == 0 else reverse('admin:login')
            response = self.client.post(url,
                {'username': self.alisa.username, 'password': 'wrong'},
                HTTP_X_FORWARDED_FOR=f'192.0.2.{i}')
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('login'),
            {'username': self.alisa.username, 'password': self.password})
        self.assertEqual(response.status_code, 429)
        response = self.client.post(reverse('login'),
            {'username': self.boris.username, 'password': self.password})
        self.assertEqual(response.status_code, 302)

    @override_settings(LOGIN_RATE_LIMIT_AT_PROXY=False)
    def test_direct_mode_does_not_trust_spoofed_forwarded_addresses(self):
        self.client.logout()
        for i in range(40):
            self.client.post(reverse('login'), {'username': f'unknown-{i}', 'password': 'wrong'},
                             HTTP_X_FORWARDED_FOR=f'192.0.2.{i}')
        response = self.client.post(reverse('login'),
            {'username': self.alisa.username, 'password': self.password},
            HTTP_X_FORWARDED_FOR='198.51.100.1')
        self.assertEqual(response.status_code, 429)
