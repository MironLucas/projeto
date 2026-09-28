from django.db import migrations


def copiar_imagens(apps, schema_editor):
    """A imagem única de cada item vira a primeira mídia da lista nova."""
    ArquivoItemAgenda = apps.get_model('core', 'ArquivoItemAgenda')
    MidiaItemAgenda = apps.get_model('core', 'MidiaItemAgenda')
    for arquivo in ArquivoItemAgenda.objects.select_related('item').iterator():
        conteudo = bytes(arquivo.conteudo)
        MidiaItemAgenda.objects.create(
            item=arquivo.item, tipo=arquivo.item.imagem_tipo or 'image/jpeg',
            tamanho=len(conteudo), posicao=0, conteudo=conteudo,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_midias_da_agenda'),
    ]

    operations = [
        migrations.RunPython(copiar_imagens, migrations.RunPython.noop),
    ]
