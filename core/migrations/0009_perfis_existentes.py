from django.db import migrations


def criar_perfis(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Perfil = apps.get_model('core', 'Perfil')
    for usuario in User.objects.filter(perfil__isnull=True):
        Perfil.objects.create(usuario=usuario, conta=usuario, papel='admin')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_perfis'),
    ]

    operations = [
        migrations.RunPython(criar_perfis, migrations.RunPython.noop),
    ]
