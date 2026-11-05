import os
import uuid
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from portal.models import (Announcement, Deadline, Discipline, Group, LearningResult,
                           Lesson, Notification, Profile, RequestHistory, StudentRequest)


class Command(BaseCommand):
    help = 'Add fictional demo data without deleting requests or resetting existing passwords.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        accounts = [('alisa', 'DEMO_STUDENT_PASSWORD'), ('maks', 'DEMO_SECOND_PASSWORD'), ('curator', 'DEMO_STAFF_PASSWORD')]
        # Validate all missing credentials before modifying any data.
        for username, variable in accounts:
            if not User.objects.filter(username=username).exists():
                password = os.environ.get(variable)
                if not password:
                    raise CommandError(f'Set {variable} for initial account creation.')
                try:
                    validate_password(password, User(username=username))
                except ValidationError as exc:
                    raise CommandError(f'{variable}: ' + '; '.join(exc.messages))
        users = []
        for username, variable in accounts:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(os.environ[variable])
                user.is_staff = username == 'curator'
                user.save()
                if user.is_staff:
                    user.user_permissions.add(*Permission.objects.filter(
                        content_type__app_label='portal', codename__in=['view_studentrequest', 'change_studentrequest']))
            users.append(user)
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        names = ['Алгоритмы и структуры данных', 'Проектирование информационных систем',
                 'Математический анализ', 'Английский язык', 'Физическая культура',
                 'Базы данных', 'Компьютерная графика и проектирование интерактивных образовательных интерфейсов']
        disciplines = [Discipline.objects.get_or_create(name=n)[0] for n in names]
        announcement, _ = Announcement.objects.get_or_create(title='Кампус, в котором тебя слышат', defaults={
            'body': 'Открыта запись на студенческую проектную мастерскую. Можно прийти со своей идеей или присоединиться к команде. '
                    'Встреча проходит в открытой зоне библиотеки. Это вымышленное объявление конкурсного прототипа.'})
        for index, user in enumerate(users[:2]):
            group, _ = Group.objects.get_or_create(name=['ИКБО-12-25', 'ДИЗ-04-24'][index])
            Profile.objects.get_or_create(user=user, defaults={
                'full_name': ['Алиса Андреевна Лебедева', 'Максим Сергеевич Орлов'][index],
                'faculty': ['Институт информационных технологий', 'Институт цифрового дизайна'][index],
                'program': ['09.03.02 · Информационные системы и технологии', '54.03.01 · Дизайн'][index],
                'year': 2 + index, 'group': group, 'student_number': f'DEMO-2026-00{index+1}',
            })
            for offset in range(14):
                day = monday + timedelta(days=offset)
                if day.weekday() >= 5:
                    continue
                for slot in range(3):
                    discipline = disciplines[(offset + slot + index * 3) % len(disciplines)]
                    moved = slot == 1 and day.weekday() in (1, 3)
                    cancelled = slot == 2 and day.weekday() == 4
                    Lesson.objects.get_or_create(group=group, date=day, start=[time(9, 0), time(11, 45) if moved else time(10, 40), time(14, 0)][slot],
                        discipline=discipline, defaults={
                            'end': [time(10, 30), time(13, 15) if moved else time(12, 10), time(15, 30)][slot],
                            'kind': ['Лекция', 'Практика', 'Лабораторная'][slot],
                            'room': ['А-304 · корпус А', 'Б-215 · корпус Б', 'А-108 · корпус А'][slot],
                            'teacher': ['Ирина Павловна Соколова', 'Дмитрий Викторович Крылов', 'Ольга Игоревна Миронова'][slot],
                            'cancelled': cancelled,
                            'old_start': time(10, 40) if moved else None,
                            'old_room': 'А-201 · корпус А' if moved else '',
                            'change_note': 'Преподаватель на конференции. Занятие отменено.' if cancelled else
                                           'Изменены время и аудитория. Проверьте маршрут между корпусами.' if moved else '',
                        })
            states = ['grade', 'grade', 'pass', 'pending', 'empty', 'debt']
            for i, state in enumerate(states):
                LearningResult.objects.get_or_create(user=user, discipline=disciplines[(i+index)%len(disciplines)], defaults={
                    'state': state, 'grade': ([5, 4] if index == 0 else [3, 4])[i] if i < 2 else None,
                    'exam_date': today+timedelta(days=8+i) if state in ['pending','empty'] else None,
                    'note': 'Нужно сдать лабораторную работу № 2. Уточните время пересдачи у преподавателя.' if state == 'debt' else '',
                })
            for i, title in enumerate(['Отправить проектную работу', 'Подготовить лабораторную № 3', 'Повторить темы к экзамену']):
                due = timezone.make_aware(datetime.combine(today+timedelta(days=[0,2,7][i]), time(18,0)))
                deadline, _ = Deadline.objects.get_or_create(user=user, title=title, defaults={
                    'discipline': disciplines[(i+index)%len(disciplines)], 'due': due})
                Notification.objects.get_or_create(user=user, kind='deadline', title=f'Учебная задача: {title}', defaults={
                    'body': f'Срок: {timezone.localtime(deadline.due):%d.%m.%Y %H:%M}. Подробности в успеваемости.'})
            samples = [('clarify','destination','Уточните полное название организации — места требования.'),
                       ('work','study','Обращение зарегистрировано и передано специалисту.'),
                       ('ready','study','Демонстрационная справка готова. В прототипе выдача файлов не предусмотрена.')] if index == 0 else [
                       ('rejected','application','В заявлении не указан предмет обращения. Создайте новое с описанием вопроса.'),
                       ('sent','study','Обращение принято в очередь.')]
            for i, (status, kind, comment) in enumerate(samples):
                key = uuid.uuid5(uuid.NAMESPACE_URL, f'campus-demo:{user.username}:{i}')
                item, created = StudentRequest.objects.get_or_create(idempotency_key=key, defaults={
                    'user': user, 'kind': kind, 'status': status,
                    'destination': 'Учебный проект «Открытая мастерская»' if kind == 'destination' else '',
                    'text': 'Прошу рассмотреть учебный вопрос в рамках конкурсной демонстрации.' if kind == 'application' else '',
                    'created_at': timezone.now()-timedelta(days=2, hours=i)})
                if created:
                    RequestHistory.objects.create(request=item, status='sent', actor=user, created_at=item.created_at, comment='Заявка отправлена студентом.')
                    if status != 'sent':
                        RequestHistory.objects.create(request=item, status=status, actor=users[2], comment=comment)
                    Notification.objects.create(user=user, kind='request', title=f'{item.number}: {item.get_status_display()}',
                                                body=comment, related_request=item)
            Notification.objects.get_or_create(user=user, announcement=announcement, defaults={
                'kind': 'announcement', 'title': announcement.title, 'body': announcement.body})
            Notification.objects.get_or_create(user=user, kind='schedule', title='Изменения в расписании группы ' + group.name, defaults={
                'body': 'Во вторник и четверг вторая пара перенесена с 10:40 на 11:45, из А-201 в Б-215. '
                        'В пятницу третья пара отменена. Даты смотрите в расписании.'})
        self.stdout.write(self.style.SUCCESS(
            'Demo prepared: alisa, maks; staff: curator. Existing passwords and requests preserved. '
            f'Schedule: {monday:%d.%m.%Y} – {monday+timedelta(days=13):%d.%m.%Y}.'))
