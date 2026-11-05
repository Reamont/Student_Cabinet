import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Group(models.Model):
    name = models.CharField('Группа', max_length=40, unique=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField('ФИО', max_length=200)
    faculty = models.CharField('Факультет', max_length=200)
    program = models.CharField('Направление', max_length=200)
    year = models.PositiveSmallIntegerField('Курс', default=2)
    group = models.ForeignKey(Group, on_delete=models.PROTECT)
    student_number = models.CharField('Номер билета', max_length=40, unique=True)

    def __str__(self):
        return self.full_name


class Discipline(models.Model):
    name = models.CharField('Дисциплина', max_length=240, unique=True)

    def __str__(self):
        return self.name


class Lesson(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT)
    date = models.DateField()
    start = models.TimeField()
    end = models.TimeField()
    kind = models.CharField(max_length=50, default='Лекция')
    room = models.CharField(max_length=80)
    teacher = models.CharField(max_length=180)
    cancelled = models.BooleanField(default=False)
    old_start = models.TimeField(null=True, blank=True)
    old_room = models.CharField(max_length=80, blank=True)
    change_note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ['date', 'start']
        constraints = [models.CheckConstraint(condition=Q(end__gt=models.F('start')), name='lesson_positive_duration')]


class LearningResult(models.Model):
    class State(models.TextChoices):
        GRADE = 'grade', 'Оценка'
        PASS = 'pass', 'Зачёт'
        PENDING = 'pending', 'Ожидается результат'
        EMPTY = 'empty', 'Нет данных'
        DEBT = 'debt', 'Академическая задолженность'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT)
    state = models.CharField(max_length=12, choices=State.choices)
    grade = models.PositiveSmallIntegerField(null=True, blank=True)
    exam_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(Q(state='grade', grade__isnull=False, grade__gte=2, grade__lte=5) | (~Q(state='grade') & Q(grade__isnull=True))),
            name='grade_only_for_graded_result')]


class Deadline(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT)
    title = models.CharField(max_length=240)
    due = models.DateTimeField()
    done = models.BooleanField(default=False)

    class Meta:
        ordering = ['due']


class StudentRequest(models.Model):
    class Kind(models.TextChoices):
        STUDY = 'study', 'Справка об обучении'
        DESTINATION = 'destination', 'Справка для места требования'
        APPLICATION = 'application', 'Заявление в деканат'

    class Status(models.TextChoices):
        SENT = 'sent', 'Отправлена'
        WORK = 'work', 'В работе'
        CLARIFY = 'clarify', 'Нужно уточнение'
        READY = 'ready', 'Готова'
        REJECTED = 'rejected', 'Отклонена'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_requests')
    kind = models.CharField('Тип', max_length=20, choices=Kind.choices)
    destination = models.CharField('Место требования', max_length=200, blank=True)
    text = models.TextField('Текст обращения', max_length=3000, blank=True)
    status = models.CharField('Статус', max_length=12, choices=Status.choices, default=Status.SENT)
    created_at = models.DateTimeField(default=timezone.now)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'

    @property
    def number(self):
        return f'ПК-{self.pk:05d}'

    def __str__(self):
        return f'{self.number} · {self.get_kind_display()}'


class RequestHistory(models.Model):
    request = models.ForeignKey(StudentRequest, on_delete=models.CASCADE, related_name='history')
    status = models.CharField(max_length=12, choices=StudentRequest.Status.choices)
    comment = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['created_at', 'pk']


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    published_at = models.DateTimeField(default=timezone.now)


class Notification(models.Model):
    class Kind(models.TextChoices):
        ANNOUNCEMENT = 'announcement', 'Объявления'
        SCHEDULE = 'schedule', 'Расписание'
        DEADLINE = 'deadline', 'Дедлайны'
        REQUEST = 'request', 'Заявки'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=240)
    body = models.TextField()
    announcement = models.ForeignKey(Announcement, null=True, blank=True, on_delete=models.CASCADE)
    related_request = models.ForeignKey(StudentRequest, null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
