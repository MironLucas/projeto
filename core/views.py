import secrets
from datetime import datetime, time, timedelta
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
    periodo_chave, desde, ate, periodo_label = _resolver_periodo(
        request.GET.get('periodo', 'hoje'),
        request.GET.get('inicio'),
        request.GET.get('fim'),
    )

    instagram = InstagramConnection.objects.filter(user=request.user).first()
    midias = []
    curtidas_total = 0
    comentarios_total = 0
    seguidores_ganhos = None

    if instagram:
        _renovar_token_se_necessario(instagram)
        midias = _buscar_midias_periodo(instagram, desde, ate)
        curtidas_total = sum(m.get('like_count') or 0 for m in midias)
        comentarios_total = sum(m.get('comments_count') or 0 for m in midias)
        seguidores_ganhos = _buscar_seguidores_periodo(instagram, desde, ate)

    return render(request, 'core/dashboard.html', {
        'active_menu': 'dashboard',
        'instagram': instagram,
        'midias': midias,
        'curtidas_total': curtidas_total,
        'comentarios_total': comentarios_total,
        'seguidores_ganhos': seguidores_ganhos,
        'periodo_atual': periodo_chave,
        'periodo_label': periodo_label,
        'inicio_custom': request.GET.get('inicio', ''),
        'fim_custom': request.GET.get('fim', ''),
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


def _resolver_periodo(chave, inicio_str, fim_str):
    agora = timezone.localtime(timezone.now())
    hoje = agora.date()

    if chave == 'semana':
        inicio = hoje - timedelta(days=hoje.weekday())
        fim = hoje
        label = 'Esta semana'
    elif chave == 'mes':
        inicio = hoje.replace(day=1)
        fim = hoje
        label = 'Este mês'
    elif chave == 'mes_passado':
        primeiro_dia_atual = hoje.replace(day=1)
        fim = primeiro_dia_atual - timedelta(days=1)
        inicio = fim.replace(day=1)
        label = 'Mês passado'
    elif chave == 'periodo' and inicio_str and fim_str:
        try:
            inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
        except ValueError:
            chave, inicio, fim = 'hoje', hoje, hoje
        else:
            label = f'{inicio.strftime("%d/%m/%Y")} – {fim.strftime("%d/%m/%Y")}'
    else:
        chave, inicio, fim = 'hoje', hoje, hoje

    if chave == 'hoje':
        label = 'Hoje'

    tz = timezone.get_current_timezone()
    desde = timezone.make_aware(datetime.combine(inicio, time.min), tz)
    ate = timezone.make_aware(datetime.combine(fim, time.max), tz)
    if fim >= hoje:
        ate = agora

    return chave, desde, ate, label


def _parse_timestamp_instagram(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%dT%H:%M:%S%z')
    except ValueError:
        return None


def _buscar_midias_periodo(instagram, desde, ate, max_paginas=5):
    if not instagram.instagram_user_id:
        return []

    midias = []
    url = f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/media'
    params = {
        'fields': 'id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count',
        'access_token': instagram.access_token,
        'limit': 25,
    }

    try:
        for _ in range(max_paginas):
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            corpo = resp.json()

            chegou_antes_do_periodo = False
            for item in corpo.get('data', []):
                publicado_em = _parse_timestamp_instagram(item.get('timestamp'))
                if publicado_em is None:
                    continue
                if publicado_em < desde:
                    chegou_antes_do_periodo = True
                    break
                if publicado_em <= ate:
                    midias.append(item)

            if chegou_antes_do_periodo:
                break

            proxima_url = corpo.get('paging', {}).get('next')
            if not proxima_url:
                break
            url, params = proxima_url, None
    except requests.RequestException:
        pass

    return midias


def _buscar_seguidores_periodo(instagram, desde, ate):
    if not instagram.instagram_user_id:
        return None
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/insights', params={
            'metric': 'follower_count',
            'period': 'day',
            'since': int(desde.timestamp()),
            'until': int(ate.timestamp()),
            'access_token': instagram.access_token,
        }, timeout=10)
        resp.raise_for_status()
        valores = resp.json()['data'][0]['values']
        return sum(v.get('value', 0) for v in valores)
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


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
