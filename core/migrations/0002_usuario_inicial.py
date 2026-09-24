from django.contrib.auth.hashers import make_password
from django.db import migrations


def criar_usuario_inicial(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    if not User.objects.filter(username='mironlucas').exists():
        User.objects.create(
            username='mironlucas',
            password=make_password('bp102030'),
            is_staff=True,
            is_superuser=True,
        )


def remover_usuario_inicial(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    User.objects.filter(username='mironlucas').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(criar_usuario_inicial, remover_usuario_inicial),
    ]
