from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from .models import Discipline, Group, Lesson, Notification, Profile, RequestDraft, StudentRequest


class DemoProfileMigrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('alisa')
        self.group = Group.objects.create(name='ИКБО-12-25')
        self.profile = Profile.objects.create(user=self.user, group=self.group,
            full_name='Алиса Андреевна Лебедева', faculty='Институт информационных технологий',
            program='09.03.02 · Информационные системы и технологии', year=2,
            student_number='DEMO-2026-001')
        self.lesson = Lesson.objects.create(group=self.group,
            discipline=Discipline.objects.create(name='Тестовая дисциплина'),
            date=timezone.localdate(), start='09:00', end='10:30', room='А-1', teacher='Демо-преподаватель')
        self.request = StudentRequest.objects.create(user=self.user, kind='study')
        self.draft = RequestDraft.objects.create(user=self.user, text='Сохранить черновик')
        self.notice = Notification.objects.create(user=self.user, kind='schedule',
            title='Изменения в расписании группы ИКБО-12-25', read_at=timezone.now())

    def migrate_data(self):
        migration = import_module('portal.migrations.0004_update_alisa_demo_profile')
        migration.update_demo_profile(apps, connection.schema_editor())

    def test_existing_demo_profile_changes_without_losing_data(self):
        password = self.user.password
        read_at = self.notice.read_at
        self.migrate_data()
        self.migrate_data()
        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.notice.refresh_from_db()
        self.assertEqual(self.profile.faculty, 'Институт информативных технологий')
        self.assertEqual(self.profile.program, '10.10.10 · Информационные системы и технологии')
        self.assertEqual(self.profile.group.name, 'АБВГ-01-02')
        self.assertEqual(self.profile.group_id, self.group.pk)
        self.assertTrue(Lesson.objects.filter(pk=self.lesson.pk, group_id=self.profile.group_id).exists())
        self.assertTrue(StudentRequest.objects.filter(pk=self.request.pk, user=self.user).exists())
        self.assertTrue(RequestDraft.objects.filter(pk=self.draft.pk, user=self.user).exists())
        self.assertEqual(self.user.password, password)
        self.assertEqual(self.notice.read_at, read_at)
        self.assertIn('АБВГ-01-02', self.notice.title)

    def test_existing_target_group_retains_access_to_lessons(self):
        target = Group.objects.create(name='АБВГ-01-02')
        self.migrate_data()
        self.profile.refresh_from_db()
        self.lesson.refresh_from_db()
        self.assertEqual(self.profile.group_id, target.pk)
        self.assertEqual(self.lesson.group_id, target.pk)

    def test_unrelated_account_is_not_overwritten(self):
        self.profile.student_number = 'CUSTOM-01'
        self.profile.save()
        self.migrate_data()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.faculty, 'Институт информационных технологий')
        self.assertEqual(self.profile.group.name, 'ИКБО-12-25')
