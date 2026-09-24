import calendar
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ItemAgenda

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
    itens = ItemAgenda.objects.filter(usuario=request.user, data__range=(semanas[0][0], semanas[-1][-1]))
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
    })


@require_POST
@login_required
def adicionar_item(request):
    data = _ler_data(request.POST.get('data'))
    titulo = request.POST.get('titulo', '').strip()[:200]
    if not data or not titulo:
        return redirect('programacao')
    horario = None
    try:
        horario = datetime.strptime(request.POST.get('horario', ''), '%H:%M').time()
    except ValueError:
        pass
    ItemAgenda.objects.create(usuario=request.user, data=data, horario=horario, titulo=titulo)
    return _voltar_para(data)


@require_POST
@login_required
def alternar_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.user)
    item.concluido = not item.concluido
    item.save(update_fields=['concluido'])
    return _voltar_para(item.data)


@require_POST
@login_required
def excluir_item(request, item_id):
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.user)
    item.delete()
    return _voltar_para(item.data)


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
