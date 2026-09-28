import calendar
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ArquivoItemAgenda, ItemAgenda
from .quadro import CORES_LISTA, CORES_VALIDAS, LIMITE_MIDIA_MB, TAMANHO_MAXIMO_LEGENDA

COR_PADRAO = CORES_LISTA[0][0]
TIPOS_DE_IMAGEM = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

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
        'itens_selecionado': por_dia.get(selecionado, []),
        'cores': CORES_LISTA,
        'cor_padrao': COR_PADRAO,
        'tipos_de_imagem': ','.join(sorted(TIPOS_DE_IMAGEM)),
        'limite_midia_mb': LIMITE_MIDIA_MB,
        'tamanho_maximo_legenda': TAMANHO_MAXIMO_LEGENDA,
    })


@require_POST
@login_required
def adicionar_item(request):
    data = _ler_data(request.POST.get('data'))
    titulo = request.POST.get('titulo', '').strip()[:200]
    if not data or not titulo:
        return _responder(request, data, 'Preencha o título e o dia.')
    imagem = request.FILES.get('imagem')
    erro = _validar_imagem(imagem)
    if erro:
        return _responder(request, data, erro)
    with transaction.atomic():
        item = ItemAgenda.objects.create(
            usuario=request.conta, data=data, titulo=titulo, cor=_ler_cor(request), legenda=_ler_legenda(request),
        )
        if imagem:
            _salvar_imagem(item, imagem)
    return _responder(request, data)


@require_POST
@login_required
def editar_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    imagem = request.FILES.get('imagem')
    erro = _validar_imagem(imagem)
    if erro:
        return _responder(request, item.data, erro)
    titulo = request.POST.get('titulo', '').strip()[:200]
    if titulo:
        item.titulo = titulo
    item.data = _ler_data(request.POST.get('data')) or item.data
    item.cor = _ler_cor(request, item.cor)
    item.legenda = _ler_legenda(request)
    with transaction.atomic():
        if imagem:
            _salvar_imagem(item, imagem)
        elif request.POST.get('remover_imagem') and item.imagem_tipo:
            ArquivoItemAgenda.objects.filter(item=item).delete()
            item.imagem_tipo = ''
        item.save()
    return _responder(request, item.data)


@login_required
def imagem_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    arquivo = get_object_or_404(ArquivoItemAgenda, item=item)
    resposta = HttpResponse(bytes(arquivo.conteudo), content_type=item.imagem_tipo)
    resposta['Content-Disposition'] = 'inline'
    resposta['Cache-Control'] = 'private, max-age=86400'
    return resposta


@require_POST
@login_required
def alternar_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    item.concluido = not item.concluido
    item.save(update_fields=['concluido'])
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


def _ler_legenda(request):
    return request.POST.get('legenda', '').strip()[:TAMANHO_MAXIMO_LEGENDA]


def _validar_imagem(imagem):
    if not imagem:
        return None
    if imagem.content_type not in TIPOS_DE_IMAGEM:
        return 'Envie uma imagem JPG, PNG, GIF ou WebP.'
    if imagem.size > LIMITE_MIDIA_MB * 1024 * 1024:
        return f'A imagem tem mais de {LIMITE_MIDIA_MB} MB. Envie uma versão menor.'
    return None


def _salvar_imagem(item, imagem):
    ArquivoItemAgenda.objects.update_or_create(item=item, defaults={'conteudo': b''.join(imagem.chunks())})
    item.imagem_tipo = imagem.content_type
    item.imagem_versao += 1
    item.save(update_fields=['imagem_tipo', 'imagem_versao'])


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
