import calendar
import logging
import secrets
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .graficos import DIAS_SEMANA, intervalos_do_grafico, montar_grafico
from .models import InstagramConnection, SeguidoresDia

INSTAGRAM_AUTH_URL = 'https://api.instagram.com/oauth/authorize'
INSTAGRAM_TOKEN_URL = 'https://api.instagram.com/oauth/access_token'
INSTAGRAM_LONG_LIVED_TOKEN_URL = 'https://graph.instagram.com/access_token'
INSTAGRAM_REFRESH_TOKEN_URL = 'https://graph.instagram.com/refresh_access_token'
INSTAGRAM_GRAPH_URL = 'https://graph.instagram.com'
INSTAGRAM_SCOPES = 'instagram_business_basic,instagram_business_manage_insights'

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
        request.GET.get('periodo', 'mes'),
        request.GET.get('inicio'),
        request.GET.get('fim'),
    )

    instagram = InstagramConnection.objects.filter(user=request.user).first()
    contexto = {
        'active_menu': 'dashboard',
        'instagram': instagram,
        'periodo_atual': periodo.chave,
        'periodo_label': periodo.label,
        'label_comparacao': periodo.label_comparacao,
        'inicio_custom': request.GET.get('inicio', ''),
        'fim_custom': request.GET.get('fim', ''),
    }
    if not instagram:
        return render(request, 'core/dashboard.html', contexto)

    try:
        contexto.update(_dados_do_dashboard(instagram, periodo))
    except Exception:
        # Proteção na fronteira com a API: uma resposta inesperada do Instagram não pode derrubar a página.
        logger.exception('Falha ao montar o dashboard com os dados do Instagram')
        contexto['erro_instagram'] = True
    return render(request, 'core/dashboard.html', contexto)


def _dados_do_dashboard(instagram, periodo):
    _renovar_token_se_necessario(instagram)
    foto_perfil, seguidores_total = _buscar_perfil_atual(instagram)
    _sincronizar_seguidores(instagram)

    hoje = timezone.localdate()
    subtitulo, intervalos = intervalos_do_grafico(
        periodo.chave, _data_local(periodo.desde), _data_local(periodo.ate), hoje,
    )
    inicio_busca = periodo.anterior_desde
    if intervalos:
        inicio_busca = min(inicio_busca, _inicio_do_dia(intervalos[0].inicio))

    midias, midias_cobertas_desde = _buscar_midias_desde(instagram, inicio_busca)
    midias_recentes = midias[:12]
    for midia in midias_recentes:
        midia['capa'] = midia.get('thumbnail_url') or midia.get('media_url') or ''
    _adicionar_visualizacoes(instagram, midias_recentes)
    motivos = Counter(m['visualizacoes_motivo'] for m in midias_recentes if m.get('visualizacoes_motivo'))

    curtidas_total, comentarios_total = _somar_engajamento(midias, periodo.desde, periodo.ate)
    curtidas_anterior, comentarios_anterior = _somar_engajamento(midias, periodo.anterior_desde, periodo.anterior_ate)

    seguidores_por_dia = _seguidores_por_dia(instagram, _data_local(inicio_busca), hoje)
    seguidores_ganhos, _ = _somar_seguidores(
        seguidores_por_dia, _data_local(periodo.desde), _data_local(periodo.ate), hoje,
    )
    seguidores_anterior, anterior_completo = _somar_seguidores(
        seguidores_por_dia, _data_local(periodo.anterior_desde), _data_local(periodo.anterior_ate), hoje,
    )
    visualizacoes_total = _buscar_visualizacoes_conta(instagram, periodo.desde, periodo.ate)
    visualizacoes_anterior = _buscar_visualizacoes_conta(instagram, periodo.anterior_desde, periodo.anterior_ate)

    return {
        'foto_perfil': foto_perfil,
        'seguidores_total': seguidores_total,
        'midias': midias_recentes,
        'aviso_visualizacoes': motivos.most_common(1)[0][0] if motivos else None,
        'curtidas_total': curtidas_total,
        'comentarios_total': comentarios_total,
        'seguidores_ganhos': seguidores_ganhos,
        'comparacao_seguidores': _comparar(seguidores_ganhos, seguidores_anterior if anterior_completo else None),
        'comparacao_curtidas': _comparar(curtidas_total, curtidas_anterior),
        'comparacao_comentarios': _comparar(comentarios_total, comentarios_anterior),
        'visualizacoes_total': visualizacoes_total,
        'comparacao_visualizacoes': _comparar(visualizacoes_total, visualizacoes_anterior),
        'grafico_seguidores': montar_grafico(
            subtitulo, intervalos, *_serie_seguidores(seguidores_por_dia, intervalos, hoje),
        ),
        'grafico_curtidas': montar_grafico(
            subtitulo, intervalos, *_serie_curtidas(midias, intervalos, midias_cobertas_desde),
        ),
    }


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
    # Semana e mês em andamento são comparados com os mesmos dias do período anterior
    # (ex.: 01 a 24/09 vs. 01 a 24/08), para a comparação ser justa.
    agora = timezone.localtime(timezone.now())
    hoje = agora.date()

    if chave == 'hoje':
        inicio = fim = hoje
        anterior_inicio = anterior_fim = hoje - timedelta(days=1)
        label, label_comparacao = 'Hoje', 'vs. ontem'
    elif chave == 'semana':
        inicio = hoje - timedelta(days=hoje.weekday())
        anterior_inicio, anterior_fim = inicio - timedelta(days=7), hoje - timedelta(days=7)
        fim = hoje
        label = 'Esta semana'
        label_comparacao = f'vs. semana passada até {DIAS_SEMANA[hoje.weekday()]}'
    elif chave == 'periodo' and inicio_str and fim_str:
        try:
            inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
        except ValueError:
            chave = 'mes'
        else:
            if inicio > fim:
                inicio, fim = fim, inicio
            dias = (fim - inicio).days + 1
            anterior_inicio, anterior_fim = inicio - timedelta(days=dias), fim - timedelta(days=dias)
            label = f'{inicio:%d/%m/%Y} – {fim:%d/%m/%Y}'
            label_comparacao = 'vs. dia anterior' if dias == 1 else f'vs. {dias} dias anteriores'
    else:
        chave = 'mes'

    # "Este mês" é o padrão, inclusive para períodos desconhecidos ou datas inválidas.
    if chave == 'mes':
        inicio, fim = hoje.replace(day=1), hoje
        anterior_inicio, anterior_fim = _mesmo_dia_mes_anterior(inicio), _mesmo_dia_mes_anterior(hoje)
        label = 'Este mês'
        label_comparacao = f'vs. mês passado até {anterior_fim:%d/%m}'

    return Periodo(
        chave=chave,
        label=label,
        label_comparacao=label_comparacao,
        desde=_inicio_do_dia(inicio),
        ate=min(_fim_do_dia(fim), agora),
        anterior_desde=_inicio_do_dia(anterior_inicio),
        anterior_ate=_fim_do_dia(anterior_fim),
    )


def _mesmo_dia_mes_anterior(dia):
    ano, mes = (dia.year, dia.month - 1) if dia.month > 1 else (dia.year - 1, 12)
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return dia.replace(year=ano, month=mes, day=min(dia.day, ultimo_dia))


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


def _buscar_midias_desde(instagram, desde, max_paginas=8):
    """Devolve (mídias, cobertas_desde). cobertas_desde é None quando a busca alcançou `desde`;
    senão é a data do post mais antigo obtido, e antes dela os números ficam incompletos."""
    # A API devolve as mídias da mais nova para a mais antiga; paginamos até cobrir o início do período.
    if not instagram.instagram_user_id:
        return [], None

    midias = []
    url = f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/media'
    params = {
        'fields': 'id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count',
        'access_token': instagram.access_token,
        'limit': 25,
    }

    completo = False
    try:
        for _ in range(max_paginas):
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            corpo = resp.json()

            pagina = corpo.get('data', [])
            midias.extend(pagina)
            proxima_url = corpo.get('paging', {}).get('next')
            mais_antiga = _parse_timestamp_instagram(pagina[-1].get('timestamp')) if pagina else None

            if not pagina or not proxima_url or (mais_antiga is not None and mais_antiga < desde):
                completo = True
                break
            url, params = proxima_url, None
    except (requests.RequestException, ValueError):
        logger.warning('Falha ao buscar as publicações do Instagram')

    if completo or not midias:
        return midias, None
    return midias, _parse_timestamp_instagram(midias[-1].get('timestamp'))


def _adicionar_visualizacoes(instagram, midias):
    # A métrica views vale para fotos, carrosséis e vídeos.
    if not midias:
        return

    def buscar(midia):
        try:
            resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{midia["id"]}/insights', params={
                'metric': 'views',
                'access_token': instagram.access_token,
            }, timeout=8)
        except requests.RequestException:
            logger.warning('Falha de rede ao buscar visualizações da mídia %s', midia['id'])
            return None, 'O Instagram não respondeu a tempo. Recarregue a página para tentar de novo.'
        if not resp.ok:
            logger.warning(
                'Instagram recusou visualizações da mídia %s (HTTP %s): %s',
                midia['id'], resp.status_code, resp.text[:300],
            )
            return None, _motivo_erro_insights(resp)
        try:
            metrica = resp.json()['data'][0]
            valor = (metrica.get('total_value') or {}).get('value')
            if valor is None:
                valor = metrica['values'][0]['value']
            return valor, None
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            logger.warning('Resposta inesperada de visualizações da mídia %s: %s', midia['id'], resp.text[:300])
            return None, 'O Instagram devolveu uma resposta em formato inesperado.'

    with ThreadPoolExecutor(max_workers=6) as executor:
        for midia, (visualizacoes, motivo) in zip(midias, executor.map(buscar, midias)):
            midia['visualizacoes'] = visualizacoes
            midia['visualizacoes_motivo'] = motivo


def _motivo_erro_insights(resp):
    try:
        erro = resp.json().get('error') or {}
    except (ValueError, AttributeError):
        erro = {}
    if not isinstance(erro, dict):
        erro = {}
    codigo, subcodigo = erro.get('code'), erro.get('error_subcode')
    mensagem = erro.get('message') or ''

    if subcodigo == 2108006:
        return 'O Instagram não fornece estatísticas de posts publicados antes da conta virar profissional.'
    if codigo in (10, 200) or 'permission' in mensagem.lower():
        return ('A permissão de estatísticas não foi concedida. '
                'Desconecte e conecte o Instagram de novo aceitando todas as permissões.')
    if codigo == 190:
        return 'A conexão com o Instagram expirou. Desconecte e conecte de novo.'
    return f'O Instagram não informou as visualizações: {mensagem or f"HTTP {resp.status_code}"}'


def _buscar_visualizacoes_conta(instagram, desde, ate):
    """Quantas vezes o conteúdo da conta foi exibido entre desde e ate (posts, reels e stories)."""
    # O Instagram aceita no máximo 30 dias por consulta; períodos maiores são somados em partes.
    total = 0
    inicio = desde
    while inicio < ate:
        fim = min(inicio + timedelta(days=30), ate)
        try:
            resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/insights', params={
                'metric': 'views',
                'period': 'day',
                'metric_type': 'total_value',
                'since': int(inicio.timestamp()),
                'until': int(fim.timestamp()),
                'access_token': instagram.access_token,
            }, timeout=10)
        except requests.RequestException:
            logger.warning('Falha de rede ao buscar visualizações da conta')
            return None
        if not resp.ok:
            logger.warning('Instagram recusou visualizações da conta (HTTP %s): %s', resp.status_code, resp.text[:300])
            return None
        try:
            total += resp.json()['data'][0]['total_value']['value']
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning('Resposta inesperada de visualizações da conta: %s', resp.text[:300])
            return None
        inicio = fim
    return total


def _buscar_perfil_atual(instagram):
    """Devolve (url da foto de perfil, total de seguidores)."""
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/me', params={
            'fields': 'profile_picture_url,followers_count',
            'access_token': instagram.access_token,
        }, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
    except (requests.RequestException, ValueError):
        return '', None
    return dados.get('profile_picture_url', ''), dados.get('followers_count')


def _sincronizar_seguidores(instagram):
    # O Instagram só informa novos seguidores dos últimos 30 dias; guardamos cada dia
    # no banco para o histórico dos gráficos crescer além disso.
    if not instagram.instagram_user_id:
        return
    agora = timezone.now()
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/insights', params={
            'metric': 'follower_count',
            'period': 'day',
            'since': int((agora - timedelta(days=29)).timestamp()),
            'until': int(agora.timestamp()),
            'access_token': instagram.access_token,
        }, timeout=10)
    except requests.RequestException:
        logger.warning('Falha de rede ao buscar novos seguidores')
        return
    if not resp.ok:
        logger.warning('Instagram recusou novos seguidores (HTTP %s): %s', resp.status_code, resp.text[:300])
        return
    try:
        valores = resp.json()['data'][0]['values']
    except (KeyError, IndexError, ValueError):
        logger.warning('Resposta inesperada de novos seguidores: %s', resp.text[:300])
        return

    for item in valores:
        fim_do_dia = _parse_timestamp_instagram(item.get('end_time'))
        if fim_do_dia is None or item.get('value') is None:
            continue
        # end_time marca o fim do dia medido (meia-noite do dia seguinte).
        dia = fim_do_dia.astimezone(dt_timezone.utc).date() - timedelta(days=1)
        SeguidoresDia.objects.update_or_create(
            instagram_user_id=instagram.instagram_user_id,
            data=dia,
            defaults={'novos_seguidores': item['value']},
        )


def _seguidores_por_dia(instagram, inicio, fim):
    linhas = SeguidoresDia.objects.filter(
        instagram_user_id=instagram.instagram_user_id, data__gte=inicio, data__lte=fim,
    ).values_list('data', 'novos_seguidores')
    return dict(linhas)


def _somar_seguidores(por_dia, inicio, fim, hoje):
    """Devolve (total, completo). completo indica que todos os dias já encerrados têm dado."""
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    presentes = [por_dia[d] for d in dias if d in por_dia]
    if not presentes:
        return None, False
    completo = all(d in por_dia for d in dias if d < hoje)
    return sum(presentes), completo


def _serie_seguidores(por_dia, intervalos, hoje):
    valores, parciais = [], []
    for intervalo in intervalos:
        total, completo = _somar_seguidores(por_dia, intervalo.inicio, intervalo.fim, hoje)
        valores.append(total)
        parciais.append(total is not None and not completo)
    return valores, parciais


def _serie_curtidas(midias, intervalos, cobertas_desde):
    corte = _data_local(cobertas_desde) if cobertas_desde else None
    datas = [(_data_publicacao(m), m.get('like_count') or 0) for m in midias]
    valores, parciais = [], []
    for intervalo in intervalos:
        if corte and intervalo.fim < corte:
            valores.append(None)
            parciais.append(False)
            continue
        valores.append(sum(curtidas for dia, curtidas in datas if dia and intervalo.inicio <= dia <= intervalo.fim))
        parciais.append(bool(corte and intervalo.inicio < corte))
    return valores, parciais


def _data_local(momento):
    return timezone.localtime(momento).date()


def _data_publicacao(midia):
    publicado_em = _parse_timestamp_instagram(midia.get('timestamp'))
    return _data_local(publicado_em) if publicado_em else None


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
