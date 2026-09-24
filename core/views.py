import calendar
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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

DIAS_SEMANA = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']

logger = logging.getLogger(__name__)


@dataclass
class Periodo:
    chave: str
    label: str
    label_comparacao: str
    desde: datetime
    ate: datetime
    anterior_desde: datetime
    anterior_ate: datetime


@login_required
def dashboard(request):
    periodo = _resolver_periodo(
        request.GET.get('periodo', 'hoje'),
        request.GET.get('inicio'),
        request.GET.get('fim'),
    )

    instagram = InstagramConnection.objects.filter(user=request.user).first()
    midias_recentes = []
    foto_perfil = ''
    curtidas_total = comentarios_total = 0
    seguidores_ganhos = None
    comparacao_seguidores = comparacao_curtidas = comparacao_comentarios = None

    if instagram:
        _renovar_token_se_necessario(instagram)
        foto_perfil = _buscar_foto_perfil(instagram)
        midias = _buscar_midias_desde(instagram, periodo.anterior_desde)
        midias_recentes = midias[:12]
        _adicionar_visualizacoes(instagram, midias_recentes)

        curtidas_total, comentarios_total = _somar_engajamento(midias, periodo.desde, periodo.ate)
        curtidas_anterior, comentarios_anterior = _somar_engajamento(
            midias, periodo.anterior_desde, periodo.anterior_ate,
        )
        seguidores_ganhos = _buscar_seguidores_periodo(instagram, periodo.desde, periodo.ate)
        seguidores_anterior = _buscar_seguidores_periodo(instagram, periodo.anterior_desde, periodo.anterior_ate)

        comparacao_seguidores = _comparar(seguidores_ganhos, seguidores_anterior)
        comparacao_curtidas = _comparar(curtidas_total, curtidas_anterior)
        comparacao_comentarios = _comparar(comentarios_total, comentarios_anterior)

    return render(request, 'core/dashboard.html', {
        'active_menu': 'dashboard',
        'instagram': instagram,
        'foto_perfil': foto_perfil,
        'midias': midias_recentes,
        'curtidas_total': curtidas_total,
        'comentarios_total': comentarios_total,
        'seguidores_ganhos': seguidores_ganhos,
        'comparacao_seguidores': comparacao_seguidores,
        'comparacao_curtidas': comparacao_curtidas,
        'comparacao_comentarios': comparacao_comentarios,
        'periodo_atual': periodo.chave,
        'periodo_label': periodo.label,
        'label_comparacao': periodo.label_comparacao,
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
    # Períodos em andamento são comparados com o mesmo trecho do período anterior
    # (ex.: hoje até 11:25 vs. ontem até 11:25), para a comparação ser justa.
    agora = timezone.localtime(timezone.now())
    hoje = agora.date()
    hora = agora.strftime('%H:%M')

    if chave == 'semana':
        desde, ate = _inicio_do_dia(hoje - timedelta(days=hoje.weekday())), agora
        anterior_desde, anterior_ate = desde - timedelta(days=7), ate - timedelta(days=7)
        label = 'Esta semana'
        label_comparacao = f'vs. semana passada até {DIAS_SEMANA[hoje.weekday()]} {hora}'
    elif chave == 'mes':
        desde, ate = _inicio_do_dia(hoje.replace(day=1)), agora
        anterior_desde, anterior_ate = _mesmo_momento_mes_anterior(desde), _mesmo_momento_mes_anterior(ate)
        label = 'Este mês'
        label_comparacao = f'vs. mês passado até {anterior_ate:%d/%m} {hora}'
    elif chave == 'mes_passado':
        ultimo_dia = hoje.replace(day=1) - timedelta(days=1)
        desde, ate = _inicio_do_dia(ultimo_dia.replace(day=1)), _fim_do_dia(ultimo_dia)
        ultimo_dia_anterior = ultimo_dia.replace(day=1) - timedelta(days=1)
        anterior_desde = _inicio_do_dia(ultimo_dia_anterior.replace(day=1))
        anterior_ate = _fim_do_dia(ultimo_dia_anterior)
        label, label_comparacao = 'Mês passado', 'vs. mês anterior'
    elif chave == 'periodo' and inicio_str and fim_str:
        try:
            inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
        except ValueError:
            chave = 'hoje'
        else:
            if inicio > fim:
                inicio, fim = fim, inicio
            dias = (fim - inicio).days + 1
            desde, ate = _inicio_do_dia(inicio), min(_fim_do_dia(fim), agora)
            anterior_desde, anterior_ate = desde - timedelta(days=dias), ate - timedelta(days=dias)
            label = f'{inicio:%d/%m/%Y} – {fim:%d/%m/%Y}'
            label_comparacao = 'vs. dia anterior' if dias == 1 else f'vs. {dias} dias anteriores'
    else:
        chave = 'hoje'

    if chave == 'hoje':
        desde, ate = _inicio_do_dia(hoje), agora
        anterior_desde, anterior_ate = desde - timedelta(days=1), ate - timedelta(days=1)
        label, label_comparacao = 'Hoje', f'vs. ontem até {hora}'

    return Periodo(
        chave=chave,
        label=label,
        label_comparacao=label_comparacao,
        desde=desde,
        ate=ate,
        anterior_desde=anterior_desde,
        anterior_ate=anterior_ate,
    )


def _mesmo_momento_mes_anterior(momento):
    ano, mes = (momento.year, momento.month - 1) if momento.month > 1 else (momento.year - 1, 12)
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return momento.replace(year=ano, month=mes, day=min(momento.day, ultimo_dia))


def _inicio_do_dia(dia):
    return timezone.make_aware(datetime.combine(dia, time.min))


def _fim_do_dia(dia):
    return timezone.make_aware(datetime.combine(dia, time.max))


def _comparar(atual, anterior):
    if atual is None or anterior is None:
        return None
    diferenca = atual - anterior
    if diferenca > 0:
        direcao = 'up'
    elif diferenca < 0:
        direcao = 'down'
    else:
        direcao = 'equal'
    return {'direcao': direcao, 'valor': abs(diferenca)}


def _somar_engajamento(midias, desde, ate):
    no_periodo = [m for m in midias if _publicado_entre(m, desde, ate)]
    curtidas = sum(m.get('like_count') or 0 for m in no_periodo)
    comentarios = sum(m.get('comments_count') or 0 for m in no_periodo)
    return curtidas, comentarios


def _parse_timestamp_instagram(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%dT%H:%M:%S%z')
    except ValueError:
        return None


def _publicado_entre(midia, desde, ate):
    publicado_em = _parse_timestamp_instagram(midia.get('timestamp'))
    return publicado_em is not None and desde <= publicado_em <= ate


def _buscar_midias_desde(instagram, desde, max_paginas=5):
    # A API devolve as mídias da mais nova para a mais antiga; paginamos até cobrir o início do período.
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

            pagina = corpo.get('data', [])
            if not pagina:
                break
            midias.extend(pagina)

            mais_antiga = _parse_timestamp_instagram(pagina[-1].get('timestamp'))
            if mais_antiga is not None and mais_antiga < desde:
                break

            proxima_url = corpo.get('paging', {}).get('next')
            if not proxima_url:
                break
            url, params = proxima_url, None
    except (requests.RequestException, ValueError):
        pass

    return midias


def _adicionar_visualizacoes(instagram, midias):
    videos = [m for m in midias if m.get('media_type') == 'VIDEO']
    if not videos:
        return

    def buscar(midia):
        try:
            resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{midia["id"]}/insights', params={
                'metric': 'views',
                'access_token': instagram.access_token,
            }, timeout=8)
        except requests.RequestException:
            logger.warning('Falha de rede ao buscar visualizações da mídia %s', midia['id'])
            return None
        if not resp.ok:
            logger.warning(
                'Instagram recusou visualizações da mídia %s (HTTP %s): %s',
                midia['id'], resp.status_code, resp.text[:300],
            )
            return None
        try:
            metrica = resp.json()['data'][0]
            if 'total_value' in metrica:
                return metrica['total_value']['value']
            return metrica['values'][0]['value']
        except (KeyError, IndexError, ValueError):
            logger.warning('Resposta inesperada de visualizações da mídia %s: %s', midia['id'], resp.text[:300])
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        for midia, visualizacoes in zip(videos, executor.map(buscar, videos)):
            midia['visualizacoes'] = visualizacoes


def _buscar_foto_perfil(instagram):
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/me', params={
            'fields': 'profile_picture_url',
            'access_token': instagram.access_token,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get('profile_picture_url', '')
    except (requests.RequestException, ValueError):
        return ''


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
