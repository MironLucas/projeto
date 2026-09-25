import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import ArquivoCartao, Cartao, ListaTarefas

LISTAS_INICIAIS = ['A fazer', 'Fazendo', 'Feito']
CORES_LISTA = [
    ('#7c5cff', 'Roxo'), ('#3b82f6', 'Azul'), ('#00d4ff', 'Ciano'), ('#3ddc84', 'Verde'),
    ('#f5a524', 'Amarelo'), ('#ff7a45', 'Laranja'), ('#f5426f', 'Rosa'), ('#5c6288', 'Cinza'),
]
CORES_VALIDAS = {cor for cor, _ in CORES_LISTA}
TIPOS_DE_MIDIA = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'video/mp4', 'video/quicktime', 'video/webm',
}
LIMITE_MIDIA_MB = 25
TAMANHO_MAXIMO_LEGENDA = 2200  # mesmo limite de legenda do Instagram


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
        'cores_lista': CORES_LISTA,
        'tipos_de_midia': ','.join(sorted(TIPOS_DE_MIDIA)),
        'limite_midia_mb': LIMITE_MIDIA_MB,
        'tamanho_maximo_legenda': TAMANHO_MAXIMO_LEGENDA,
    })


@require_POST
@login_required
def criar_lista(request):
    titulo = request.POST.get('titulo', '').strip()[:80]
    if titulo:
        ultima = ListaTarefas.objects.filter(usuario=request.user).aggregate(m=Max('posicao'))['m']
        lista = ListaTarefas.objects.create(
            usuario=request.user, titulo=titulo, posicao=0 if ultima is None else ultima + 1,
        )
        return _voltar_para(lista)
    return redirect('tarefas')


@require_POST
@login_required
def editar_lista(request, lista_id):
    lista = get_object_or_404(ListaTarefas, id=lista_id, usuario=request.user)
    titulo = request.POST.get('titulo', '').strip()[:80]
    if titulo:
        lista.titulo = titulo
    if request.POST.get('cor') in CORES_VALIDAS:
        lista.cor = request.POST['cor']
    lista.save(update_fields=['titulo', 'cor'])
    return _voltar_para(lista)


@require_POST
@login_required
def mover_lista(request, lista_id):
    lista = get_object_or_404(ListaTarefas, id=lista_id, usuario=request.user)
    with transaction.atomic():
        listas = list(ListaTarefas.objects.filter(usuario=request.user).exclude(id=lista.id).select_for_update())
        listas.insert(_posicao(request, len(listas)), lista)
        for indice, item in enumerate(listas):
            item.posicao = indice
        ListaTarefas.objects.bulk_update(listas, ['posicao'])
    return _responder(request, lista)


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
    arquivo = request.FILES.get('arquivo')
    erro = _validar_midia(arquivo)
    if erro:
        messages.error(request, erro)
    elif titulo:
        with transaction.atomic():
            ultima = lista.cartoes.aggregate(m=Max('posicao'))['m']
            cartao = Cartao.objects.create(
                lista=lista,
                titulo=titulo,
                legenda=request.POST.get('legenda', '').strip()[:TAMANHO_MAXIMO_LEGENDA],
                posicao=0 if ultima is None else ultima + 1,
            )
            if arquivo:
                _salvar_midia(cartao, arquivo)
    return _voltar_para(lista)


@require_POST
@login_required
def editar_cartao(request, cartao_id):
    cartao = get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user)
    arquivo = request.FILES.get('arquivo')
    erro = _validar_midia(arquivo)
    if erro:
        messages.error(request, erro)
        return _voltar_para(cartao.lista)

    with transaction.atomic():
        titulo = request.POST.get('titulo', '').strip()[:300]
        if titulo:
            cartao.titulo = titulo
        cartao.legenda = request.POST.get('legenda', '').strip()[:TAMANHO_MAXIMO_LEGENDA]

        destino = _lista_do_usuario(request, request.POST.get('lista'))
        if destino and destino.id != cartao.lista_id:
            ultima = destino.cartoes.aggregate(m=Max('posicao'))['m']
            cartao.lista = destino
            cartao.posicao = 0 if ultima is None else ultima + 1

        if arquivo:
            _salvar_midia(cartao, arquivo)
        elif request.POST.get('remover_midia'):
            ArquivoCartao.objects.filter(cartao=cartao).delete()
            cartao.midia_tipo, cartao.midia_nome, cartao.midia_tamanho = '', '', 0
        cartao.save()
    return _voltar_para(cartao.lista)


@require_POST
@login_required
def mover_cartao(request, cartao_id):
    cartao = get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user)
    destino = _lista_do_usuario(request, request.POST.get('lista'))
    if not destino:
        raise Http404('Coluna inválida')

    with transaction.atomic():
        cartoes = list(destino.cartoes.exclude(id=cartao.id).select_for_update())
        cartoes.insert(_posicao(request, len(cartoes)), cartao)
        cartao.lista = destino
        for indice, item in enumerate(cartoes):
            item.posicao = indice
        Cartao.objects.bulk_update(cartoes, ['lista', 'posicao'])
    return _responder(request, destino)


@require_POST
@login_required
def excluir_cartao(request, cartao_id):
    cartao = get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user)
    lista = cartao.lista
    cartao.delete()
    return _voltar_para(lista)


@login_required
def arquivo_cartao(request, cartao_id):
    cartao = get_object_or_404(Cartao, id=cartao_id, lista__usuario=request.user)
    arquivo = get_object_or_404(ArquivoCartao, cartao=cartao)
    dados = bytes(arquivo.conteudo)
    total = len(dados)
    inicio, fim, status = 0, total - 1, 200

    # Suporte a Range: o Safari (iPhone) só toca vídeo se o servidor aceitar pedidos por partes.
    faixa = re.fullmatch(r'bytes=(\d*)-(\d*)', request.headers.get('Range', ''))
    if faixa and (faixa[1] or faixa[2]):
        if faixa[1]:
            inicio = int(faixa[1])
            fim = min(int(faixa[2]), total - 1) if faixa[2] else total - 1
        else:
            inicio = max(0, total - int(faixa[2]))
        if inicio > fim:
            resposta = HttpResponse(status=416)
            resposta['Content-Range'] = f'bytes */{total}'
            return resposta
        status = 206

    resposta = HttpResponse(dados[inicio:fim + 1], status=status, content_type=cartao.midia_tipo)
    resposta['Accept-Ranges'] = 'bytes'
    resposta['Content-Length'] = str(fim - inicio + 1)
    resposta['Content-Disposition'] = 'inline'
    resposta['Cache-Control'] = 'private, max-age=86400'
    if status == 206:
        resposta['Content-Range'] = f'bytes {inicio}-{fim}/{total}'
    return resposta


def _validar_midia(arquivo):
    if not arquivo:
        return None
    if arquivo.content_type not in TIPOS_DE_MIDIA:
        return 'Envie uma imagem (JPG, PNG, GIF ou WebP) ou um vídeo (MP4, MOV ou WebM).'
    if arquivo.size > LIMITE_MIDIA_MB * 1024 * 1024:
        return f'O arquivo tem mais de {LIMITE_MIDIA_MB} MB. Envie uma versão menor.'
    return None


def _salvar_midia(cartao, arquivo):
    ArquivoCartao.objects.update_or_create(cartao=cartao, defaults={'conteudo': b''.join(arquivo.chunks())})
    cartao.midia_tipo = arquivo.content_type
    cartao.midia_nome = arquivo.name[:255]
    cartao.midia_tamanho = arquivo.size
    cartao.midia_versao += 1
    cartao.save(update_fields=['midia_tipo', 'midia_nome', 'midia_tamanho', 'midia_versao'])


def _lista_do_usuario(request, valor):
    try:
        return ListaTarefas.objects.get(id=int(valor), usuario=request.user)
    except (TypeError, ValueError, ListaTarefas.DoesNotExist):
        return None


def _posicao(request, maximo):
    try:
        posicao = int(request.POST.get('posicao'))
    except (TypeError, ValueError):
        return maximo
    return max(0, min(posicao, maximo))


def _responder(request, lista):
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'ok': True})
    return _voltar_para(lista)


def _voltar_para(lista):
    return redirect(f'{reverse("tarefas")}#lista-{lista.id}')
