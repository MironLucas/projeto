import secrets
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import InstagramConnection

INSTAGRAM_AUTH_URL = 'https://api.instagram.com/oauth/authorize'
INSTAGRAM_TOKEN_URL = 'https://api.instagram.com/oauth/access_token'
INSTAGRAM_LONG_LIVED_TOKEN_URL = 'https://graph.instagram.com/access_token'
INSTAGRAM_REFRESH_TOKEN_URL = 'https://graph.instagram.com/refresh_access_token'
INSTAGRAM_GRAPH_URL = 'https://graph.instagram.com'
INSTAGRAM_SCOPES = 'instagram_business_basic,instagram_business_manage_insights'


@login_required
def dashboard(request):
    instagram = InstagramConnection.objects.filter(user=request.user).first()
    midias = []
    if instagram:
        _renovar_token_se_necessario(instagram)
        midias = _buscar_midias_recentes(instagram)
    return render(request, 'core/dashboard.html', {
        'active_menu': 'dashboard',
        'instagram': instagram,
        'midias': midias,
    })


@login_required
def programacao(request):
    return render(request, 'core/programacao.html', {'active_menu': 'programacao'})


@login_required
def tarefas(request):
    return render(request, 'core/tarefas.html', {'active_menu': 'tarefas'})


@login_required
def instagram_conectar(request):
    if not settings.INSTAGRAM_CLIENT_ID or not settings.INSTAGRAM_CLIENT_SECRET or not settings.INSTAGRAM_REDIRECT_URI:
        messages.error(
            request,
            'A integração com o Instagram ainda não foi configurada neste servidor. '
            'Defina INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET e INSTAGRAM_REDIRECT_URI '
            'nas variáveis de ambiente.',
        )
        return redirect('dashboard')

    state = secrets.token_urlsafe(24)
    request.session['instagram_oauth_state'] = state

    params = {
        'client_id': settings.INSTAGRAM_CLIENT_ID,
        'redirect_uri': settings.INSTAGRAM_REDIRECT_URI,
        'scope': INSTAGRAM_SCOPES,
        'response_type': 'code',
        'state': state,
    }
    return redirect(f'{INSTAGRAM_AUTH_URL}?{urlencode(params)}')


@login_required
def instagram_callback(request):
    erro = request.GET.get('error_description') or request.GET.get('error')
    if erro:
        messages.error(request, f'Conexão com o Instagram cancelada: {erro}.')
        return redirect('dashboard')

    state_recebido = request.GET.get('state')
    state_esperado = request.session.pop('instagram_oauth_state', None)
    code = request.GET.get('code')

    if not code or not state_recebido or state_recebido != state_esperado:
        messages.error(request, 'Não foi possível validar a conexão com o Instagram. Tente novamente.')
        return redirect('dashboard')

    try:
        token_curto = _trocar_code_por_token_curto(code)
        token_longo = _trocar_token_curto_por_longo(token_curto['access_token'])
        perfil = _buscar_perfil(token_longo['access_token'])
    except requests.RequestException:
        messages.error(request, 'Falha ao conversar com a API do Instagram. Tente novamente em alguns minutos.')
        return redirect('dashboard')
    except (KeyError, ValueError):
        messages.error(request, 'O Instagram retornou uma resposta inesperada. Tente novamente.')
        return redirect('dashboard')

    InstagramConnection.objects.update_or_create(
        user=request.user,
        defaults={
            'instagram_user_id': str(perfil.get('id', '')),
            'instagram_username': perfil.get('username', ''),
            'account_type': perfil.get('account_type', ''),
            'access_token': token_longo['access_token'],
            'token_expires_at': timezone.now() + timedelta(seconds=token_longo.get('expires_in', 5184000)),
        },
    )
    messages.success(request, f'Conta @{perfil.get("username", "")} conectada com sucesso.')
    return redirect('dashboard')


@login_required
def instagram_desconectar(request):
    InstagramConnection.objects.filter(user=request.user).delete()
    messages.info(request, 'Conta do Instagram desconectada.')
    return redirect('dashboard')


def _trocar_code_por_token_curto(code):
    resp = requests.post(INSTAGRAM_TOKEN_URL, data={
        'client_id': settings.INSTAGRAM_CLIENT_ID,
        'client_secret': settings.INSTAGRAM_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'redirect_uri': settings.INSTAGRAM_REDIRECT_URI,
        'code': code,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _trocar_token_curto_por_longo(token_curto):
    resp = requests.get(INSTAGRAM_LONG_LIVED_TOKEN_URL, params={
        'grant_type': 'ig_exchange_token',
        'client_secret': settings.INSTAGRAM_CLIENT_SECRET,
        'access_token': token_curto,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _buscar_perfil(access_token):
    resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/me', params={
        'fields': 'id,username,account_type,media_count',
        'access_token': access_token,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _buscar_midias_recentes(instagram):
    if not instagram.instagram_user_id:
        return []
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/media', params={
            'fields': 'id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count',
            'access_token': instagram.access_token,
            'limit': 12,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get('data', [])
    except requests.RequestException:
        return []


def _renovar_token_se_necessario(instagram):
    if not instagram.token_expires_at:
        return
    if instagram.token_expires_at - timezone.now() > timedelta(days=5):
        return
    try:
        resp = requests.get(INSTAGRAM_REFRESH_TOKEN_URL, params={
            'grant_type': 'ig_refresh_token',
            'access_token': instagram.access_token,
        }, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        instagram.access_token = dados['access_token']
        instagram.token_expires_at = timezone.now() + timedelta(seconds=dados.get('expires_in', 5184000))
        instagram.save(update_fields=['access_token', 'token_expires_at'])
    except (requests.RequestException, KeyError):
        pass
