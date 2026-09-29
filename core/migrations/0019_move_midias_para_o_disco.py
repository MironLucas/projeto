import mimetypes

from django.core.files.base import ContentFile
from django.db import migrations


def mover_para_o_disco(apps, schema_editor):
    """As mídias que estavam dentro do banco passam a ser arquivos em MEDIA_ROOT."""
    MidiaItemAgenda = apps.get_model('core', 'MidiaItemAgenda')
    pendentes = MidiaItemAgenda.objects.filter(arquivo='').exclude(conteudo=None).values_list('id', flat=True)
    for midia_id in list(pendentes):
        midia = MidiaItemAgenda.objects.get(id=midia_id)
        extensao = mimetypes.guess_extension(midia.tipo) or ''
        midia.arquivo.save(f'midia{extensao}', ContentFile(bytes(midia.conteudo)), save=False)
        midia.conteudo = None
        midia.save(update_fields=['arquivo', 'conteudo'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_midias_em_disco'),
    ]

    operations = [
        migrations.RunPython(mover_para_o_disco, migrations.RunPython.noop),
    ]
