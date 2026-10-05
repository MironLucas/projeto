import calendar
import json
from datetime import date, datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .arquivos import responder_arquivo_em_disco
from .models import ItemAgenda, MidiaItemAgenda
from .permissoes import abrir_conta
from .quadro import CORES_LISTA, CORES_VALIDAS, TAMANHO_MAXIMO_LEGENDA, TIPOS_DE_MIDIA

COR_PADRAO = CORES_LISTA[0][0]
MIDIAS_POR_ITEM = 10
# Vídeos gravados no celular passam fácil de 25 MB; como ficam em disco, o limite deles é bem maior.
LIMITE_IMAGEM_MB = 25
LIMITE_VIDEO_MB = 500
ERRO_FORMATO = 'Escolha o formato: Carrossel, Estático, Reels, Stories ou Outro.'

MESES_EXTENSO = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
                 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
DIAS_EXTENSO = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
CABECALHO_SEMANA = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb']
ITENS_POR_DIA_NO_CALENDARIO = 3


@login_required
def programacao(request):
    hoje = timezone.localdate()
    primeiro_dia = _ler_mes(request.GET.get('mes')) or hoje.replace(day=1)
    selecionado = _ler_data(request.GET.get('dia'))
    if not selecionado or (selecionado.year, selecionado.month) != (primeiro_dia.year, primeiro_dia.month):
        selecionado = hoje if (hoje.year, hoje.month) == (primeiro_dia.year, primeiro_dia.month) else primeiro_dia

    semanas = calendar.Calendar(firstweekday=6).monthdatescalendar(primeiro_dia.year, primeiro_dia.month)
    itens = ItemAgenda.objects.filter(usuario=request.conta, data__range=(semanas[0][0], semanas[-1][-1]))
    por_dia = {}
    for item in itens:
        por_dia.setdefault(item.data, []).append(item)
    itens_selecionado = list(
        ItemAgenda.objects.filter(usuario=request.conta, data=selecionado)
        .annotate(total_comentarios=Count('comentarios')).prefetch_related('midias')
    )
    for item in itens_selecionado:
        # A janela de edição recebe a lista de mídias do item para montar a galeria.
        item.midias_json = json.dumps([
            {'id': midia.id, 'url': reverse('agenda_midia', args=[midia.id]), 'video': midia.e_video}
            for midia in item.midias.all()
        ])

    return render(request, 'core/programacao.html', {
        'active_menu': 'programacao',
        'titulo_mes': f'{MESES_EXTENSO[primeiro_dia.month - 1].capitalize()} {primeiro_dia.year}',
        'cabecalho_semana': CABECALHO_SEMANA,
        'semanas': [[_celula(dia, primeiro_dia, hoje, selecionado, por_dia.get(dia, [])) for dia in semana]
                    for semana in semanas],
        'mes_atual': f'{primeiro_dia:%Y-%m}',
        'mes_anterior': f'{_somar_meses(primeiro_dia, -1):%Y-%m}',
        'mes_seguinte': f'{_somar_meses(primeiro_dia, 1):%Y-%m}',
        'mes_de_hoje': f'{hoje:%Y-%m}',
        'selecionado': selecionado,
        'titulo_selecionado': _data_por_extenso(selecionado),
        'itens_selecionado': itens_selecionado,
        'cores': CORES_LISTA,
        'cor_padrao': COR_PADRAO,
        'tipos_de_midia': ','.join(sorted(TIPOS_DE_MIDIA)),
        'limite_imagem_mb': LIMITE_IMAGEM_MB,
        'limite_video_mb': LIMITE_VIDEO_MB,
        'midias_por_item': MIDIAS_POR_ITEM,
        'formatos': ItemAgenda.FORMATOS,
        'tamanho_maximo_legenda': TAMANHO_MAXIMO_LEGENDA,
    })


@require_POST
@login_required
def adicionar_item(request):
    data = _ler_data(request.POST.get('data'))
    titulo = request.POST.get('titulo', '').strip()[:200]
    if not data or not titulo:
        return _responder(request, data, 'Preencha o título e o dia.')
    formato = _ler_formato(request)
    if not formato:
        return _responder(request, data, ERRO_FORMATO)
    novas = request.FILES.getlist('midias')
    erro = _validar_midias(novas, ja_existentes=0)
    if erro:
        return _responder(request, data, erro)
    with transaction.atomic():
        item = ItemAgenda.objects.create(
            usuario=request.conta, data=data, titulo=titulo, formato=formato,
            cor=_ler_cor(request), legenda=_ler_legenda(request),
        )
        _salvar_midias(item, novas)
    return _responder(request, data)


@require_POST
@login_required
def editar_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    formato = _ler_formato(request)
    if not formato:
        return _responder(request, item.data, ERRO_FORMATO)
    remover = item.midias.filter(id__in=_ler_ids(request.POST.getlist('remover_midias')))
    novas = request.FILES.getlist('midias')
    erro = _validar_midias(novas, ja_existentes=item.midias.count() - remover.count())
    if erro:
        return _responder(request, item.data, erro)
    titulo = request.POST.get('titulo', '').strip()[:200]
    if titulo:
        item.titulo = titulo
    item.data = _ler_data(request.POST.get('data')) or item.data
    item.cor = _ler_cor(request, item.cor)
    item.legenda = _ler_legenda(request)
    item.formato = formato
    with transaction.atomic():
        remover.delete()
        _salvar_midias(item, novas)
        item.save()
    return _responder(request, item.data)


@login_required
def abrir_item(request, item_id):
    """Link de um item (compartilhado ou do sininho): abre a conta dele e a programação com o card aberto."""
    item = ItemAgenda.objects.filter(id=item_id).first()
    if not item or not any(perfil.conta_id == item.usuario_id for perfil in request.perfis):
        messages.error(request, 'Esse post não está em nenhuma conta que você acessa.')
        return redirect('programacao')
    abrir_conta(request, item.usuario_id)
    destino = {'mes': f'{item.data:%Y-%m}', 'dia': f'{item.data:%Y-%m-%d}', 'abrir': item.id}
    if request.GET.get('chat') == '1':
        destino['chat'] = 1
    return redirect(f"{reverse('programacao')}?{urlencode(destino)}")


@login_required
def midia_item(request, midia_id):
    midia = get_object_or_404(MidiaItemAgenda, id=midia_id, item__usuario=request.conta)
    if not midia.arquivo or not midia.arquivo.storage.exists(midia.arquivo.name):
        raise Http404('Arquivo não encontrado')
    return responder_arquivo_em_disco(request, midia.arquivo.path, midia.tipo)


@require_POST
@login_required
def alternar_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    item.concluido = not item.concluido
    item.save(update_fields=['concluido'])
    # O botão "Finalizado" marca na hora, sem recarregar a página (nem voltar para o topo).
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'ok': True, 'concluido': item.concluido})
    return _voltar_para(item.data)


@require_POST
@login_required
def excluir_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    item.delete()
    return _responder(request, item.data)


def _celula(dia, primeiro_dia, hoje, selecionado, itens):
    return {
        'data': dia,
        'numero': dia.day,
        'fora_do_mes': dia.month != primeiro_dia.month,
        'hoje': dia == hoje,
        'selecionado': dia == selecionado,
        'itens': itens[:ITENS_POR_DIA_NO_CALENDARIO],
        'restantes': max(0, len(itens) - ITENS_POR_DIA_NO_CALENDARIO),
        'total': len(itens),
        'link': _link(dia),
    }


def _link(dia):
    return f'{reverse("programacao")}?mes={dia:%Y-%m}&dia={dia:%Y-%m-%d}'


def _voltar_para(dia):
    return redirect(_link(dia))


def _responder(request, dia, erro=None):
    """A janela do item envia em segundo plano (para mostrar o progresso) e recebe JSON; sem JS, redireciona."""
    if request.headers.get('X-Requested-With') == 'fetch':
        if erro:
            return JsonResponse({'erro': erro}, status=400)
        return JsonResponse({'ok': True, 'url': _link(dia)})
    if erro:
        messages.error(request, erro)
    return _voltar_para(dia) if dia else redirect('programacao')


def _ler_formato(request):
    formato = request.POST.get('formato')
    return formato if formato in dict(ItemAgenda.FORMATOS) else None


def _ler_legenda(request):
    return request.POST.get('legenda', '').strip()[:TAMANHO_MAXIMO_LEGENDA]


def _validar_midias(arquivos, ja_existentes):
    if ja_existentes + len(arquivos) > MIDIAS_POR_ITEM:
        return f'Cada item aceita até {MIDIAS_POR_ITEM} imagens ou vídeos.'
    for arquivo in arquivos:
        if arquivo.content_type not in TIPOS_DE_MIDIA:
            return f'“{arquivo.name}” não é aceito. Envie imagens (JPG, PNG, GIF, WebP) ou vídeos (MP4, MOV, WebM).'
        limite = LIMITE_VIDEO_MB if arquivo.content_type.startswith('video/') else LIMITE_IMAGEM_MB
        if arquivo.size > limite * 1024 * 1024:
            return f'“{arquivo.name}” tem mais de {limite} MB. Envie uma versão menor.'
    return None


def _salvar_midias(item, arquivos):
    ultima = item.midias.aggregate(m=Max('posicao'))['m']
    proxima = 0 if ultima is None else ultima + 1
    for indice, arquivo in enumerate(arquivos):
        MidiaItemAgenda.objects.create(
            item=item, tipo=arquivo.content_type, nome=arquivo.name[:255], tamanho=arquivo.size,
            posicao=proxima + indice, arquivo=arquivo,
        )


def _ler_ids(valores):
    return [int(valor) for valor in valores if valor.isdigit()]


def _ler_cor(request, atual=COR_PADRAO):
    cor = request.POST.get('cor')
    return cor if cor in CORES_VALIDAS else atual


def _ler_mes(valor):
    try:
        return datetime.strptime(valor or '', '%Y-%m').date()
    except ValueError:
        return None


def _ler_data(valor):
    try:
        return datetime.strptime(valor or '', '%Y-%m-%d').date()
    except ValueError:
        return None


def _somar_meses(primeiro_dia, meses):
    indice = primeiro_dia.year * 12 + primeiro_dia.month - 1 + meses
    return date(indice // 12, indice % 12 + 1, 1)


def _data_por_extenso(dia):
    return f'{DIAS_EXTENSO[dia.weekday()].capitalize()}, {dia.day} de {MESES_EXTENSO[dia.month - 1]}'
