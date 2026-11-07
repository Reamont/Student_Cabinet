from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Discipline, Group, Lesson, Profile


@override_settings(
    SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=['testserver'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class DemoPeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = get_user_model().objects.create_user('period-student')
        cls.group = Group.objects.create(name='DEMO-PERIOD')
        Profile.objects.create(
            user=cls.student, group=cls.group, full_name='Студент Тестовый',
            faculty='Тестовый факультет', program='Тестовая программа',
            year=2, student_number='DEMO-PERIOD-01',
        )
        cls.discipline = Discipline.objects.create(name='Занятие демонстрационного периода')
        for day in (date(2026, 1, 5), date(2026, 1, 9)):
            Lesson.objects.create(
                group=cls.group, discipline=cls.discipline, date=day,
                start=time(10), end=time(11), room='Тестовая аудитория', teacher='Тестовый преподаватель',
            )

    def setUp(self):
        self.client.force_login(self.student)

    def test_expired_period_retains_dates_and_links_to_available_schedule(self):
        with patch('portal.context.timezone.localdate', return_value=date(2026, 2, 1)):
            response = self.client.get(reverse('profile'))
            self.assertContains(response, '05.01.2026 — 09.01.2026')
            self.assertContains(response, 'Демонстрационный период завершён.')
            url = reverse('schedule') + '?mode=week&date=2026-01-05'
            self.assertContains(response, 'href="' + url.replace('&', '&amp;') + '"')
            historical_schedule = self.client.get(url)
            self.assertContains(historical_schedule, self.discipline.name, count=2)
            self.assertContains(historical_schedule, 'Демонстрационный период завершён.')
        self.assertEqual(list(Lesson.objects.values_list('date', flat=True)),
                         [date(2026, 1, 5), date(2026, 1, 9)])

    def test_active_period_keeps_its_original_start_and_includes_last_day(self):
        for today in (date(2026, 1, 7), date(2026, 1, 9)):
            with self.subTest(today=today), patch('portal.context.timezone.localdate', return_value=today):
                response = self.client.get(reverse('profile'))
                self.assertContains(response, '05.01.2026 — 09.01.2026')
                self.assertNotContains(response, 'Демонстрационный период завершён.')
                self.assertFalse(response.context['demo_period']['expired'])

    def test_other_group_dates_do_not_extend_students_period(self):
        other_group = Group.objects.create(name='OTHER-PERIOD')
        Lesson.objects.create(
            group=other_group, discipline=self.discipline, date=date(2026, 3, 1),
            start=time(10), end=time(11), room='Чужая аудитория', teacher='Другой преподаватель',
        )
        with patch('portal.context.timezone.localdate', return_value=date(2026, 2, 1)):
            response = self.client.get(reverse('profile'))
        self.assertTrue(response.context['demo_period']['expired'])
        self.assertEqual(response.context['demo_period']['end'], date(2026, 1, 9))

    def test_empty_schedule_has_no_invented_period_or_expiration(self):
        Lesson.objects.filter(group=self.group).delete()
        with patch('portal.context.timezone.localdate', return_value=date(2026, 2, 1)):
            response = self.client.get(reverse('profile'))
        self.assertIsNone(response.context['demo_period'])
        self.assertNotContains(response, 'Демонстрационные данные ·')
        self.assertNotContains(response, 'Демонстрационный период завершён.')
