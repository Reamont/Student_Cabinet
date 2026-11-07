import io
import os
from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .management.commands.seed_demo import lesson_values
from .models import Discipline, Group, Lesson, Notification, StudentRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SeedScheduleTests(TestCase):
    def seed(self, today=date(2026, 11, 6)):
        credentials = {
            'DEMO_STUDENT_PASSWORD': 'Test-demo-first-48327',
            'DEMO_SECOND_PASSWORD': 'Test-demo-second-72941',
            'DEMO_STAFF_PASSWORD': 'Test-demo-staff-63295',
        }
        with patch.dict(os.environ, credentials), patch('django.utils.timezone.localdate', return_value=today):
            call_command('seed_demo', stdout=io.StringIO())

    def test_weekly_counts_repeat_through_december_and_groups_differ(self):
        self.seed()
        expected_counts = (3, 3, 5, 2, 2, 0, 0)
        groups = [Group.objects.get(name=name) for name in ('ИКБО-12-25', 'ДИЗ-04-24')]
        monday = date(2026, 11, 2)
        end = date(2026, 12, 31)
        for group in groups:
            for offset in range((end - monday).days + 1):
                day = monday + timedelta(days=offset)
                with self.subTest(group=group.name, date=day):
                    lessons = Lesson.objects.filter(group=group, date=day)
                    self.assertEqual(lessons.count(), expected_counts[day.weekday()])
                    if day != date(2026, 11, 4):
                        self.assertFalse(lessons.filter(cancelled=True).exists())
            for weekday in range(5):
                first = list(Lesson.objects.filter(group=group, date=monday+timedelta(days=weekday))
                             .values_list('start', 'end', 'discipline_id', 'kind', 'room', 'teacher'))
                following = list(Lesson.objects.filter(group=group, date=monday+timedelta(days=weekday+7))
                                 .values_list('start', 'end', 'discipline_id', 'kind', 'room', 'teacher'))
                self.assertEqual(first, following)
            self.assertEqual(Lesson.objects.filter(group=group, cancelled=True).count(), 1)
        self.assertNotEqual(
            list(Lesson.objects.filter(group=groups[0], date=monday).values_list('discipline_id', flat=True)),
            list(Lesson.objects.filter(group=groups[1], date=monday).values_list('discipline_id', flat=True)),
        )
        self.assertFalse(Lesson.objects.filter(date__gt=end).exists())

    def test_refresh_legacy_rows_preserves_custom_data_and_read_state(self):
        self.seed()
        group = Group.objects.get(name='ИКБО-12-25')
        # Recreate the obsolete third Thursday/Friday slots from the old seed.
        names = ['Алгоритмы и структуры данных', 'Проектирование информационных систем',
                 'Математический анализ', 'Английский язык', 'Физическая культура',
                 'Базы данных', 'Компьютерная графика и проектирование интерактивных образовательных интерфейсов']
        legacy_ids = []
        for day in (date(2026, 11, 5), date(2026, 11, 6), date(2027, 1, 1)):
            discipline = Discipline.objects.get(name=names[(day.weekday()+2) % len(names)])
            legacy_ids.append(Lesson.objects.create(group=group, discipline=discipline, date=day,
                                                    **lesson_values(day, 2, legacy=True)).pk)
        custom = Lesson.objects.create(group=group, discipline=Discipline.objects.create(name='Авторское занятие'),
                                       date=date(2027, 1, 1), start=time(14), end=time(15),
                                       room='Своя аудитория', teacher='Свой преподаватель')
        # A user-edited legacy-looking row must also survive refresh.
        modified_values = lesson_values(date(2026, 11, 6), 2, legacy=True)
        modified_values['change_note'] = 'Собственное изменение занятия'
        modified = Lesson.objects.create(group=group, discipline=Discipline.objects.get(name=names[6]),
                                         date=date(2026, 11, 6), **modified_values)
        alisa = get_user_model().objects.get(username='alisa')
        saved_password = alisa.password
        request = StudentRequest.objects.create(user=alisa, kind='application', text='Сохранить обращение')
        notice = Notification.objects.get(user=alisa, kind='schedule')
        notice.body = 'В пятницу третья пара отменена.'
        notice.read_at = timezone.now()
        notice.save()
        read_at = notice.read_at
        self.seed()
        self.assertFalse(Lesson.objects.filter(pk__in=legacy_ids).exists())
        self.assertTrue(Lesson.objects.filter(pk=custom.pk, room='Своя аудитория').exists())
        self.assertTrue(Lesson.objects.filter(pk=modified.pk, change_note='Собственное изменение занятия').exists())
        alisa.refresh_from_db()
        request.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(alisa.password, saved_password)
        self.assertEqual(request.text, 'Сохранить обращение')
        self.assertEqual(notice.read_at, read_at)
        self.assertIn('31.12.2026', notice.body)
        self.assertNotIn('В пятницу третья пара отменена.', notice.body)
        before = list(Lesson.objects.values())
        self.seed()
        self.assertEqual(list(Lesson.objects.values()), before)

    def test_seed_at_year_end_does_not_spill_into_next_semester(self):
        self.seed(date(2026, 12, 31))
        self.assertEqual(Lesson.objects.order_by('-date').first().date, date(2026, 12, 31))
        self.assertEqual(Lesson.objects.count(), 2 * (3+3+5+2))
        before = list(Lesson.objects.values())
        self.seed(date(2027, 1, 1))
        self.assertEqual(list(Lesson.objects.values()), before)

    def test_initial_seed_after_semester_does_not_invent_future_lessons(self):
        self.seed(date(2027, 1, 4))
        self.assertFalse(Lesson.objects.exists())
