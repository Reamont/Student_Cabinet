from django.db import migrations
from django.utils import timezone


def preserve(apps, schema_editor):
    apps.get_model('portal', 'LoginThrottle').objects.all().delete()
    User = apps.get_model('auth', 'User')
    Task = apps.get_model('portal', 'Deadline')
    Marker = apps.get_model('portal', 'DemoTaskSeed')
    Note = apps.get_model('portal', 'Notification')
    for user in User.objects.filter(username__in=['alisa', 'maks']):
        for i, title in enumerate(['Отправить проектную работу', 'Подготовить лабораторную № 3', 'Повторить темы к экзамену']):
            task = Task.objects.filter(user=user, title=title).first()
            Marker.objects.get_or_create(user=user, key=f'demo-task-{i}', defaults={'task': task})
            if task:
                notes = Note.objects.filter(user=user, kind='deadline', title='Учебная задача: ' + title)
                first = notes.first()
                if first:
                    first.related_deadline = task
                    first.save(update_fields=['related_deadline'])
                    notes.exclude(pk=first.pk).delete()
            else:
                Note.objects.filter(user=user, kind='deadline', title='Учебная задача: ' + title, related_deadline__isnull=True).delete()

    for task in Task.objects.all():
        Note.objects.update_or_create(related_deadline=task, defaults={
            'user_id': task.user_id, 'kind': 'deadline', 'title': ('Учебная задача: ' + task.title)[:240],
            'body': f'Срок: {timezone.localtime(task.due):%d.%m.%Y %H:%M}. ' +
                    ('Задача выполнена.' if task.done else 'Открой учебную задачу.'), 'read_at': None})


class Migration(migrations.Migration):
    dependencies = [('portal', '0007_notification_related_deadline_deleteddraft_and_more')]
    operations = [migrations.RunPython(preserve, migrations.RunPython.noop)]
