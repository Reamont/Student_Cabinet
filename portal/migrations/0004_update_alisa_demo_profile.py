from django.db import migrations


def update_demo_profile(apps, schema_editor):
    alias = schema_editor.connection.alias
    Profile = apps.get_model('portal', 'Profile')
    Group = apps.get_model('portal', 'Group')
    Lesson = apps.get_model('portal', 'Lesson')
    Notification = apps.get_model('portal', 'Notification')
    profile = Profile.objects.using(alias).filter(
        user__username='alisa', student_number='DEMO-2026-001').first()
    if profile is None:
        return
    old_name = 'ИКБО-12-25'
    new_name = 'АБВГ-01-02'
    group = Group.objects.using(alias).get(pk=profile.group_id)
    if group.name == old_name:
        target = Group.objects.using(alias).filter(name=new_name).first()
        if target is None:
            Group.objects.using(alias).filter(pk=group.pk).update(name=new_name)
        else:
            Lesson.objects.using(alias).filter(group_id=group.pk).update(group_id=target.pk)
            profile.group_id = target.pk
    profile.faculty = 'Институт информативных технологий'
    profile.program = '10.10.10 · Информационные системы и технологии'
    profile.save(using=alias, update_fields=['faculty', 'program', 'group'])
    Notification.objects.using(alias).filter(
        user_id=profile.user_id, kind='schedule',
        title='Изменения в расписании группы ' + old_name,
    ).update(title='Изменения в расписании группы ' + new_name)


class Migration(migrations.Migration):
    dependencies = [('portal', '0003_requestdraft')]
    operations = [migrations.RunPython(update_demo_profile, migrations.RunPython.noop)]
