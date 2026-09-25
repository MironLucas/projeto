"""Páginas públicas e avisos da Meta exigidos para a análise do app (privacidade, termos e exclusão de dados)."""
import base64
import hashlib
import hmac
import json
import logging
import secrets

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import InstagramConnection, SeguidoresDia, SolicitacaoExclusao

logger = logging.getLogger(__name__)

ATUALIZADO_EM = '25 de setembro de 2026'


def privacidade(request):
    return _pagina(request, 'core/privacidade.html', 'Política de Privacidade')


def termos(request):
    return _pagina(request, 'core/termos.html', 'Termos de Uso')


def exclusao_de_dados(request):
    codigo = request.GET.get('codigo', '').strip()
    solicitacao = SolicitacaoExclusao.objects.filter(codigo=codigo).first() if codigo else None
    return _pagina(request, 'core/exclusao_de_dados.html', 'Exclusão de dados', {
        'codigo': codigo,
        'solicitacao': solicitacao,
    })


@csrf_exempt
@require_POST
def instagram_desautorizar(request):
    """A pessoa removeu o Nextsora nas configurações do Instagram: apagamos o acesso guardado."""
    dados = _ler_signed_request(request.POST.get('signed_request', ''))
    if dados is None:
        return HttpResponseBadRequest('signed_request inválido')
    user_id = str(dados.get('user_id', ''))
    apagadas, _ = _conexoes_do_instagram(user_id).delete()
    logger.info('Instagram %s removeu o app; %s conexão(ões) apagada(s)', user_id, apagadas)
    return HttpResponse('ok')


@csrf_exempt
@require_POST
def instagram_exclusao(request):
    """A pessoa pediu à Meta a exclusão dos dados: apagamos tudo o que veio do Instagram dela."""
    dados = _ler_signed_request(request.POST.get('signed_request', ''))
    if dados is None:
        return HttpResponseBadRequest('signed_request inválido')
    user_id = str(dados.get('user_id', ''))

    conexoes = _conexoes_do_instagram(user_id)
    ids = {user_id} | set(conexoes.values_list('instagram_user_id', flat=True))
    conexoes.delete()
    SeguidoresDia.objects.filter(instagram_user_id__in=ids).delete()

    solicitacao = SolicitacaoExclusao.objects.create(
        codigo=secrets.token_hex(8),
        instagram_user_id=user_id,
        concluida_em=timezone.now(),
    )
    logger.info('Exclusão de dados do Instagram %s concluída (código %s)', user_id, solicitacao.codigo)
    url = request.build_absolute_uri(f"{reverse('exclusao_de_dados')}?codigo={solicitacao.codigo}")
    return JsonResponse({'url': url, 'confirmation_code': solicitacao.codigo})


def _pagina(request, template, titulo, contexto=None):
    return render(request, template, {
        'titulo': titulo,
        'atualizado_em': ATUALIZADO_EM,
        'contato_email': settings.CONTATO_EMAIL,
        **(contexto or {}),
    })


def _conexoes_do_instagram(user_id):
    if not user_id:
        return InstagramConnection.objects.none()
    return InstagramConnection.objects.filter(Q(instagram_user_id=user_id) | Q(instagram_conta_id=user_id))


def _ler_signed_request(valor):
    """Confere a assinatura do signed_request da Meta (HMAC-SHA256 com a chave secreta do app)."""
    segredo = settings.INSTAGRAM_CLIENT_SECRET
    if not segredo or '.' not in valor:
        return None
    assinatura_b64, conteudo_b64 = valor.split('.', 1)
    try:
        assinatura = _base64url(assinatura_b64)
        dados = json.loads(_base64url(conteudo_b64))
    except (ValueError, TypeError):
        return None
    esperada = hmac.new(segredo.encode(), conteudo_b64.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(assinatura, esperada):
        logger.warning('signed_request com assinatura inválida recebido')
        return None
    if not isinstance(dados, dict) or str(dados.get('algorithm', '')).upper() != 'HMAC-SHA256':
        return None
    return dados


def _base64url(texto):
    return base64.urlsafe_b64decode(texto + '=' * (-len(texto) % 4))
