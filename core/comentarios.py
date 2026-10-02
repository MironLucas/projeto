"""Comentários dentro de um item da programação, para combinar ajustes no post com quem revisa."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ComentarioItemAgenda, ItemAgenda

TAMANHO_MAXIMO_COMENTARIO = 2000


@login_required
def comentarios_item(request, item_id):
    # Todos com acesso à conta comentam, inclusive quem só visualiza: é assim que o cliente pede ajustes.
    item = get_object_or_404(ItemAgenda, id=item_id, usuario=request.conta)
    if request.method == 'POST':
        texto = request.POST.get('texto', '').strip()
        if not texto:
            return JsonResponse({'erro': 'Escreva o comentário antes de enviar.'}, status=400)
        if len(texto) > TAMANHO_MAXIMO_COMENTARIO:
            return JsonResponse({'erro': f'O comentário pode ter até {TAMANHO_MAXIMO_COMENTARIO} caracteres.'},
                                status=400)
        comentario = ComentarioItemAgenda.objects.create(
            item=item, autor=request.user, autor_nome=_nome(request.user), texto=texto,
        )
        return JsonResponse({'comentario': _json(comentario, request.user)}, status=201)

    comentarios = item.comentarios.all()
    return JsonResponse({'comentarios': [_json(comentario, request.user) for comentario in comentarios]})


@require_POST
@login_required
def excluir_comentario(request, comentario_id):
    # Cada pessoa apaga só o que ela mesma escreveu.
    comentario = get_object_or_404(ComentarioItemAgenda, id=comentario_id, autor=request.user,
                                   item__usuario=request.conta)
    comentario.delete()
    return JsonResponse({'ok': True})


def _json(comentario, pessoa):
    meu = comentario.autor_id is not None and comentario.autor_id == pessoa.id
    return {
        'id': comentario.id,
        'autor': comentario.autor_nome,
        'inicial': comentario.autor_nome[:1].upper(),
        'texto': comentario.texto,
        'quando': _quando(comentario.criado_em),
        'meu': meu,
        'excluir': reverse('agenda_excluir_comentario', args=[comentario.id]) if meu else '',
    }


def _quando(momento):
    local = timezone.localtime(momento)
    hoje = timezone.localdate()
    hora = f'{local:%H:%M}'
    if local.date() == hoje:
        return f'Hoje às {hora}'
    if local.date() == hoje - timedelta(days=1):
        return f'Ontem às {hora}'
    if local.year == hoje.year:
        return f'{local:%d/%m} às {hora}'
    return f'{local:%d/%m/%Y} às {hora}'


def _nome(pessoa):
    return (pessoa.get_full_name() or pessoa.username)[:150]
