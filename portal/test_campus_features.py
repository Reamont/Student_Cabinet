import io
import os
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .campus_forms import IdeaForm
from .models import (Deadline, Discipline, Group, Idea, IdeaHistory, IdeaSupport,
                     LearningResult, Lesson, Notification, Profile)


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'], TIME_ZONE='Europe/Moscow',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class CampusFeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.a = User.objects.create_user('campus-a', password='Test-only-825731')
        cls.b = User.objects.create_user('campus-b', password='Test-only-825731')
        cls.staff = User.objects.create_user('campus-staff', password='Test-only-825731', is_staff=True)
        cls.limited = User.objects.create_user('campus-limited', is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',
                                      codename__in=['view_idea', 'change_idea']))
        cls.ga = Group.objects.create(name='CAMPUS-A')
        cls.gb = Group.objects.create(name='CAMPUS-B')
        for user, group, full_name in [(cls.a, cls.ga, 'Студент А'), (cls.b, cls.gb, 'Закрытое ФИО студента Б')]:
            Profile.objects.create(user=user, group=group, full_name=full_name, faculty='Тест',
                                   program='Тест', student_number=f'CAMPUS-{user.pk}')
        cls.da = Discipline.objects.create(name='Учебный предмет А')
        cls.db = Discipline.objects.create(name='Закрытый учебный предмет Б')
        cls.day = date(2026, 11, 11)
        cls.cancelled = Lesson.objects.create(group=cls.ga, discipline=cls.da, date=cls.day,
            start=time(9), end=time(10, 30), room='А-1', teacher='Демо-преподаватель', cancelled=True)
        cls.lesson_b = Lesson.objects.create(group=cls.gb, discipline=cls.db, date=cls.day,
            start=time(9), end=time(10, 30), room='Б-1', teacher='Другой преподаватель', cancelled=True)
        cls.task = Deadline.objects.create(user=cls.a, discipline=cls.da, title='Подготовить учебный проект А',
            due=timezone.make_aware(datetime(2026, 11, 11, 18)))
        cls.done_task = Deadline.objects.create(user=cls.a, discipline=cls.da, title='Завершённая задача А',
            due=timezone.make_aware(datetime(2026, 11, 10, 18)), done=True)
        cls.task_b = Deadline.objects.create(user=cls.b, discipline=cls.db, title='Закрытая задача Б',
            due=timezone.make_aware(datetime(2026, 11, 11, 18)))
        cls.exam = LearningResult.objects.create(user=cls.a, discipline=cls.da, state='pending',
                                                exam_date=date(2026, 11, 12))
        LearningResult.objects.create(user=cls.b, discipline=cls.db, state='debt', exam_date=date(2026, 11, 12))
        cls.idea = Idea.objects.create(author=cls.a, title='Общее предложение А',
            description='Публичный текст предложения без персональных данных.')
        cls.other_idea = Idea.objects.create(author=cls.b, title='Общее предложение Б',
            description='Другая публичная идея для общего обсуждения.')
        IdeaHistory.objects.create(idea=cls.idea, status='new', comment='Предложение опубликовано.', actor=cls.a)

    def setUp(self):
        clock = patch('django.utils.timezone.now', return_value=timezone.make_aware(datetime(2026, 11, 8, 8)))
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_login(self.a)


    def idea_payload(self, **overrides):
        payload = {'title': 'Удобный формат консультаций',
            'description': 'Предлагаю проводить короткие консультации по учебным вопросам.',
            'publish': 'on', 'token': IdeaForm(user=self.a).fields['token'].initial}
        payload.update(overrides)
        return payload

    def test_semester_maps_only_current_students_events_and_links(self):
        r = self.client.get(reverse('semester'), {'month': '2026-11', 'user_id': self.b.pk})
        for title in [self.da.name, self.task.title, self.done_task.title]:
            self.assertContains(r, title)
        for title in [self.db.name, self.task_b.title, 'Закрытое ФИО студента Б']:
            self.assertNotContains(r, title)
        self.assertContains(r, reverse('grades') + f'#result-{self.exam.pk}')
        self.assertContains(r, reverse('tasks') + f'#deadline-{self.task.pk}')
        self.assertContains(r, '?date=2026-11-11')
        self.assertEqual(r.context['done_tasks'], 1)
        self.assertEqual(r.context['total_tasks'], 2)
        grades = self.client.get(reverse('grades'))
        self.assertContains(grades, f'id="result-{self.exam.pk}"')

    def test_semester_month_and_category_navigation_and_empty_state(self):
        r = self.client.get(reverse('semester'), {'month': '2026-11', 'kind': 'exams'})
        self.assertContains(r, self.da.name)
        self.assertNotContains(r, self.task.title)
        r = self.client.get(reverse('semester'), {'month': '2026-12'})
        self.assertContains(r, 'В этом месяце нет выбранных событий')
        self.assertEqual(r.context['prev_month'], date(2026, 11, 1))
        self.assertEqual(r.context['next_month'], date(2027, 1, 1))
        r = self.client.get(reverse('semester'), {'month': 'not-a-month', 'kind': 'bad'})
        self.assertEqual(r.context['month'], date(2026, 11, 1))
        self.assertEqual(r.context['selected_kind'], '')








    def test_student_can_publish_with_explicit_consent_and_no_status_injection(self):
        data = self.idea_payload(author=self.b.pk, user_id=self.b.pk, status='done', response='Поддельный ответ')
        self.assertEqual(self.client.post(reverse('idea_new'), data).status_code, 302)
        item = Idea.objects.get(title=data['title'])
        self.assertEqual(item.author_id, self.a.pk)
        self.assertEqual(item.status, 'new')
        self.assertEqual(item.response, '')
        self.assertEqual(item.history.count(), 1)
        self.assertEqual(self.client.post(reverse('idea_new'), data).status_code, 302)
        self.assertEqual(Idea.objects.filter(title=data['title']).count(), 1)
        self.assertEqual(self.client.post(reverse('idea_new'), {**data, 'title': 'Другой заголовок'}).status_code, 409)

    def test_idea_form_requires_consent_valid_text_and_owner_bound_token(self):
        data = self.idea_payload()
        for changes in [{'publish': ''}, {'title': 'Да'}, {'description': 'Мало'},
                        {'description': 'x' * 2001}, {'token': 'tampered'}]:
            r = self.client.post(reverse('idea_new'), {**data, **changes})
            self.assertEqual(r.status_code, 422)
            if 'title' not in changes:
                self.assertContains(r, data['title'], status_code=422)
        self.client.force_login(self.b)
        self.assertEqual(self.client.post(reverse('idea_new'), data).status_code, 422)
        self.assertEqual(Idea.objects.count(), 2)

    def test_public_ideas_do_not_expose_author_profiles_or_supporter_list(self):
        IdeaSupport.objects.create(idea=self.other_idea, user=self.a)
        r = self.client.get(reverse('idea_detail', args=[self.other_idea.pk]))
        self.assertContains(r, self.other_idea.description)
        self.assertNotContains(r, 'Закрытое ФИО студента Б')
        self.assertNotContains(r, 'campus-b')
        self.assertNotContains(r, self.gb.name)
        self.assertContains(r, 'Поддержали: 1')

    def test_support_is_one_per_student_and_withdrawal_affects_only_self(self):
        self.client.force_login(self.b)
        url = reverse('idea_support', args=[self.idea.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'support': '1', 'user_id': self.a.pk}).status_code, 302)
        self.assertEqual(IdeaSupport.objects.filter(idea=self.idea, user=self.b).count(), 1)
        self.assertFalse(IdeaSupport.objects.filter(idea=self.idea, user=self.a).exists())
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'support': 'bad'}).status_code, 403)
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(url, {'support': '0'}).status_code, 403)
        self.assertEqual(IdeaSupport.objects.filter(idea=self.idea).count(), 1)
        self.client.force_login(self.b)
        self.client.post(url, {'support': '0'})
        self.client.post(url, {'support': '0'})
        self.assertFalse(IdeaSupport.objects.filter(idea=self.idea).exists())

    def test_database_enforces_unique_support(self):
        IdeaSupport.objects.create(idea=self.idea, user=self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdeaSupport.objects.create(idea=self.idea, user=self.b)

    def test_idea_filters_and_popular_sort_use_actual_support(self):
        self.other_idea.status = 'planned'
        self.other_idea.save()
        IdeaSupport.objects.create(idea=self.other_idea, user=self.a)
        r = self.client.get(reverse('ideas'), {'status': 'planned'})
        self.assertContains(r, self.other_idea.title)
        self.assertNotContains(r, self.idea.title)
        r = self.client.get(reverse('ideas'), {'sort': 'popular'})
        self.assertEqual(r.context['ideas'][0].pk, self.other_idea.pk)

    def test_employee_decision_requires_response_writes_history_and_notifies(self):
        IdeaSupport.objects.create(idea=self.idea, user=self.b)
        self.client.force_login(self.staff)
        url = reverse('admin:portal_idea_change', args=[self.idea.pk])
        r = self.client.post(url, {'status': 'planned', 'response': '', '_continue': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Объясните решение студентам')
        self.idea.refresh_from_db()
        self.assertEqual(self.idea.status, 'new')
        r = self.client.post(url, {'status': 'planned', 'response': 'Включено в план конкурсного прототипа.',
                                  'author': self.b.pk, 'title': 'Подмена', '_continue': '1'})
        self.assertEqual(r.status_code, 302)
        self.idea.refresh_from_db()
        self.assertEqual(self.idea.author_id, self.a.pk)
        self.assertEqual(self.idea.title, 'Общее предложение А')
        self.assertEqual(self.idea.history.count(), 2)
        self.assertEqual(self.idea.history.last().status, 'planned')
        self.assertEqual(set(Notification.objects.filter(related_idea=self.idea).values_list('user_id', flat=True)),
                         {self.a.pk, self.b.pk})
        self.client.force_login(self.a)
        note = Notification.objects.get(user=self.a, related_idea=self.idea)
        self.assertContains(self.client.get(reverse('notification_detail', args=[note.pk])),
                            reverse('idea_detail', args=[self.idea.pk]))

    def test_students_and_unpermitted_staff_cannot_manage_idea_decisions(self):
        url = reverse('admin:portal_idea_change', args=[self.idea.pk])
        self.assertEqual(self.client.post(url, {'status': 'done', 'response': 'Подмена'}).status_code, 302)
        self.client.force_login(self.limited)
        self.assertEqual(self.client.post(url, {'status': 'done', 'response': 'Подмена'}).status_code, 403)
        self.idea.refresh_from_db()
        self.assertEqual(self.idea.status, 'new')

    def test_all_new_pages_require_login_and_mutations_require_csrf(self):
        anonymous = Client()
        for name, args in [('semester', []), ('ideas', []),
                           ('idea_new', []), ('idea_detail', [self.idea.pk])]:
            self.assertEqual(anonymous.get(reverse(name, args=args)).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.a)
        for name, args, payload in [('idea_new', [], self.idea_payload()),
                                   ('idea_support', [self.other_idea.pk], {'support': '1'})]:
            self.assertEqual(csrf_client.post(reverse(name, args=args), payload).status_code, 403)

    def test_user_text_and_public_staff_response_are_escaped(self):
        attack = '<script>alert(1)</script>'
        self.idea.title = attack
        self.idea.description = attack
        self.idea.response = attack
        self.idea.save()
        IdeaHistory.objects.create(idea=self.idea, status='new', comment=attack)
        for name, args in [('ideas', []), ('idea_detail', [self.idea.pk])]:
            r = self.client.get(reverse(name, args=args))
            self.assertNotContains(r, attack)
            self.assertContains(r, '&lt;script&gt;')

    def test_seed_updates_existing_curator_permissions_without_resetting_data(self):
        credentials = {'DEMO_STUDENT_PASSWORD': 'Test-demo-first-48327',
                       'DEMO_SECOND_PASSWORD': 'Test-demo-second-72941',
                       'DEMO_STAFF_PASSWORD': 'Test-demo-staff-63295'}
        curator = get_user_model().objects.create_user('curator', password='Keep-this-password-7925', is_staff=True)
        saved_hash = curator.password
        with patch.dict(os.environ, credentials):
            call_command('seed_demo', stdout=io.StringIO())
            before = (Idea.objects.count(), IdeaHistory.objects.count())
            call_command('seed_demo', stdout=io.StringIO())
        curator.refresh_from_db()
        self.assertEqual(curator.password, saved_hash)
        self.assertTrue(curator.has_perm('portal.change_idea'))
        self.assertTrue(curator.has_perm('portal.view_idea'))
        self.assertEqual((Idea.objects.count(), IdeaHistory.objects.count()), before)

