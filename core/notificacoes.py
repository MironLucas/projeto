"""Sininho do menu: comentários novos nos itens da programação que a pessoa ainda não leu."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .comentarios import _nome, _quando
from .models import ComentarioItemAgenda, LeituraComentarios
from .permissoes import _conta_para_o_menu

MAXIMO_NA_LISTA = 20


def nao_lidos(pessoa, contas_ids):
    """Comentários de outras pessoas, nas contas que a pessoa acessa, depois do último que ela leu em cada item."""
    lido_ate = (LeituraComentarios.objects.filter(usuario=pessoa, item=OuterRef('item_id'))
                .values('ultimo_comentario_id')[:1])
    return (ComentarioItemAgenda.objects
            .filter(item__usuario_id__in=contas_ids)
            .exclude(autor=pessoa)
            .annotate(lido_ate=Coalesce(Subquery(lido_ate), 0))
            .filter(id__gt=F('lido_ate')))


def total_nao_lidos(request):
    perfis = getattr(request, 'perfis', [])
    if not perfis:
        return 0
    return nao_lidos(request.user, [perfil.conta_id for perfil in perfis]).count()


@login_required
def notificacoes(request):
    contas = {perfil.conta_id: perfil for perfil in request.perfis}
    pendentes = nao_lidos(request.user, list(contas))
    resposta = {'total': pendentes.count()}
    if request.GET.get('lista') != '1':
        return JsonResponse(resposta)

    # Um aviso por item: quantos comentários novos e qual foi o último.
    por_item = list(pendentes.order_by().values('item_id').annotate(total=Count('id'), ultimo=Max('id'))
                    .order_by('-ultimo')[:MAXIMO_NA_LISTA])
    ultimos = {comentario.id: comentario for comentario in
               ComentarioItemAgenda.objects.filter(id__in=[linha['ultimo'] for linha in por_item])
               .select_related('autor', 'item')}
    varias_contas = len(contas) > 1
    itens = []
    for linha in por_item:
        comentario = ultimos[linha['ultimo']]
        autor = _nome(comentario.autor) if comentario.autor else comentario.autor_nome
        itens.append({
            'titulo': comentario.item.titulo,
            'autor': autor,
            'inicial': autor[:1].upper(),
            'texto': comentario.texto[:140],
            'quando': _quando(comentario.criado_em),
            'novos': linha['total'],
            'conta': _conta_para_o_menu(request, contas[comentario.item.usuario_id])['nome'] if varias_contas else '',
            'url': reverse('agenda_abrir_item', args=[comentario.item_id]) + '?chat=1',
        })
    resposta['itens'] = itens
    return JsonResponse(resposta)


@require_POST
@login_required
def marcar_todas_lidas(request):
    pendentes = nao_lidos(request.user, [perfil.conta_id for perfil in request.perfis])
    for linha in pendentes.order_by().values('item_id').annotate(ultimo=Max('id')):
        LeituraComentarios.objects.update_or_create(
            usuario=request.user, item_id=linha['item_id'], defaults={'ultimo_comentario_id': linha['ultimo']},
        )
    return JsonResponse({'ok': True, 'total': 0})
