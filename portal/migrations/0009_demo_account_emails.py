from django.db import migrations


def assign_emails(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    users = User.objects.using(schema_editor.connection.alias)
    for username in ('alisa', 'maks', 'curator'):
        email = f'{username}@campus.example.test'
        if not users.filter(email__iexact=email).exists():
            users.filter(username=username, email='').update(email=email)


class Migration(migrations.Migration):
    dependencies = [('portal', '0008_preserve_demo_tasks')]
    operations = [migrations.RunPython(assign_emails, migrations.RunPython.noop)]
