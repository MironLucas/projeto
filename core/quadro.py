from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Cartao, ListaTarefas

LISTAS_INICIAIS = ['A fazer', 'Fazendo', 'Feito']


@login_required
def tarefas(request):
    listas = ListaTarefas.objects.filter(usuario=request.user).prefetch_related('cartoes')
    if not listas.exists():
        ListaTarefas.objects.bulk_create([
            ListaTarefas(usuario=request.user, titulo=titulo, posicao=i) for i, titulo in enumerate(LISTAS_INICIAIS)
        ])
    return render(request, 'core/tarefas.html', {
        'active_menu': 'tarefas',
        'listas': list(listas.all()),
    })


@require_POST
@login_required
def criar_lista(request):
    titulo = request.POST.get('titulo', '').strip()[:80]
    if titulo:
        ultima = ListaTarefas.objects.filter(usuario=request.user).aggregate(m=Max('posicao'))['m']
        ListaTarefas.objects.create(usuario=request.user, titulo=titulo, posicao=0 if ultima is None else ultima + 1)
    return redirect('tarefas')


@require_POST
@login_required
def renomear_lista(request, lista_id):
    lista = get_object_or_404(ListaTarefas, id=lista_id, usuario=request.user)
    titulo = request.POST.get('titulo', '').strip()[:80]
    if titulo:
        lista.titulo = titulo
        lista.save(update_fields=['titulo'])
    return redirect('tarefas')


@require_POST
@login_required
def excluir_lista(request, lista_id):
    get_object_or_404(ListaTarefas, id=lista_id, usuario=request.user).delete()
    return redirect('tarefas')


@require_POST
@login_required
def criar_cartao(request, lista_id):
    lista = get_object_or_404(ListaTarefas, id=lista_id, usuario=request.user)
    titulo = request.POST.get('titulo', '').strip()[:300]
    if titulo:
        ultima = lista.cartoes.aggregate(m=Max('posicao'))['m']
        Cartao.objects.create(lista=lista, titulo=titulo, posicao=0 if ultima is None else ultima + 1)
    return _voltar_para(lista)


@require_POST
@login_required
def mover_cartao(request, cartao_id):
    cartao = get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user)
    try:
        destino_id = int(request.POST.get('lista'))
    except (TypeError, ValueError):
        raise Http404('Coluna inválida')
    destino = get_object_or_404(ListaTarefas, id=destino_id, usuario=request.user)

    with transaction.atomic():
        cartoes = list(destino.cartoes.exclude(id=cartao.id).select_for_update())
        try:
            posicao = int(request.POST.get('posicao'))
        except (TypeError, ValueError):
            posicao = len(cartoes)
        cartoes.insert(max(0, min(posicao, len(cartoes))), cartao)
        cartao.lista = destino
        for indice, item in enumerate(cartoes):
            item.posicao = indice
        Cartao.objects.bulk_update(cartoes, ['lista', 'posicao'])

    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'ok': True})
    return _voltar_para(destino)


@require_POST
@login_required
def excluir_cartao(request, cartao_id):
    get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user).delete()
    return redirect('tarefas')


def _voltar_para(lista):
    return redirect(f'{reverse("tarefas")}#lista-{lista.id}')
