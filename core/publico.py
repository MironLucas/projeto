import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .graficos import Intervalo, montar_grafico
from .models import InstagramConnection
from .views import INSTAGRAM_GRAPH_URL, _buscar_perfil_atual, _renovar_token_se_necessario

logger = logging.getLogger(__name__)

FAIXAS_ETARIAS = ['13-17', '18-24', '25-34', '35-44', '45-54', '55-64', '65+']
GENEROS = [('F', 'Feminino'), ('M', 'Masculino'), ('U', 'Não informado')]
ITENS_POR_RANKING = 7
# O Instagram informa os horários de atividade no horário do Pacífico (EUA).
FUSO_DO_INSTAGRAM = ZoneInfo('America/Los_Angeles')

PAISES = {
    'BR': 'Brasil', 'PT': 'Portugal', 'US': 'Estados Unidos', 'AR': 'Argentina', 'UY': 'Uruguai',
    'PY': 'Paraguai', 'CL': 'Chile', 'BO': 'Bolívia', 'PE': 'Peru', 'CO': 'Colômbia', 'VE': 'Venezuela',
    'EC': 'Equador', 'MX': 'México', 'CA': 'Canadá', 'GB': 'Reino Unido', 'IE': 'Irlanda', 'ES': 'Espanha',
    'FR': 'França', 'IT': 'Itália', 'DE': 'Alemanha', 'NL': 'Países Baixos', 'BE': 'Bélgica',
    'CH': 'Suíça', 'AT': 'Áustria', 'SE': 'Suécia', 'NO': 'Noruega', 'DK': 'Dinamarca', 'FI': 'Finlândia',
    'PL': 'Polônia', 'RU': 'Rússia', 'UA': 'Ucrânia', 'TR': 'Turquia', 'GR': 'Grécia', 'IL': 'Israel',
    'AE': 'Emirados Árabes Unidos', 'SA': 'Arábia Saudita', 'EG': 'Egito', 'MA': 'Marrocos',
    'ZA': 'África do Sul', 'NG': 'Nigéria', 'AO': 'Angola', 'MZ': 'Moçambique', 'CV': 'Cabo Verde',
    'IN': 'Índia', 'ID': 'Indonésia', 'PH': 'Filipinas', 'JP': 'Japão', 'CN': 'China', 'KR': 'Coreia do Sul',
    'AU': 'Austrália', 'NZ': 'Nova Zelândia', 'DO': 'República Dominicana', 'CR': 'Costa Rica', 'PA': 'Panamá',
    'GT': 'Guatemala', 'CU': 'Cuba', 'PR': 'Porto Rico', 'JM': 'Jamaica', 'HT': 'Haiti',
}


@login_required
def publico(request):
    instagram = InstagramConnection.objects.filter(user=request.conta).first()
    contexto = {'active_menu': 'publico', 'instagram': instagram}
    if instagram:
        try:
            contexto.update(_dados_do_publico(instagram))
        except Exception:
            logger.exception('Falha ao montar a página de público com os dados do Instagram')
            contexto['erro_instagram'] = True
    return render(request, 'core/publico.html', contexto)


def _dados_do_publico(instagram):
    _renovar_token_se_necessario(instagram)
    with ThreadPoolExecutor(max_workers=6) as executor:
        perfil = executor.submit(_buscar_perfil_atual, instagram)
        cidades = executor.submit(_buscar_demografia, instagram, 'city')
        paises = executor.submit(_buscar_demografia, instagram, 'country')
        idades = executor.submit(_buscar_demografia, instagram, 'age')
        generos = executor.submit(_buscar_demografia, instagram, 'gender')
        horarios = executor.submit(_buscar_horarios_ativos, instagram)

    foto_perfil, seguidores_total = perfil.result()
    return {
        'foto_perfil': foto_perfil,
        'seguidores_total': seguidores_total,
        'cidades': _bloco(cidades.result(), lambda itens: _ranking(itens, seguidores_total)),
        'paises': _bloco(paises.result(), lambda itens: _ranking(itens, seguidores_total, PAISES.get)),
        'idades': _bloco(idades.result(), _faixas_etarias),
        'generos': _bloco(generos.result(), _generos),
        'horarios': _bloco(horarios.result(), _grafico_horarios),
    }


def _bloco(resultado, montar):
    dados, motivo = resultado
    if motivo:
        return {'motivo': motivo}
    return {'dados': montar(dados)}


def _ranking(itens, seguidores_total, nomear=None):
    ordenados = sorted(itens, key=lambda item: item[1], reverse=True)[:ITENS_POR_RANKING]
    total = max(seguidores_total or 0, sum(valor for _, valor in itens))
    maior = ordenados[0][1] or 1
    return [{
        'nome': (nomear(chave) if nomear else None) or chave,
        'valor': valor,
        'percentual': valor / total * 100 if total else 0,
        'largura': valor / maior * 100,
    } for chave, valor in ordenados]


def _faixas_etarias(itens):
    por_faixa = dict(itens)
    total = sum(por_faixa.values()) or 1
    maior = max(por_faixa.values(), default=0) or 1
    return [{
        'nome': faixa,
        'valor': por_faixa.get(faixa, 0),
        'percentual': por_faixa.get(faixa, 0) / total * 100,
        'largura': por_faixa.get(faixa, 0) / maior * 100,
    } for faixa in FAIXAS_ETARIAS]


def _generos(itens):
    por_genero = dict(itens)
    total = sum(por_genero.values()) or 1
    return [{
        'codigo': codigo,
        'nome': nome,
        'valor': por_genero.get(codigo, 0),
        'percentual': por_genero.get(codigo, 0) / total * 100,
    } for codigo, nome in GENEROS if por_genero.get(codigo)]


def _grafico_horarios(medias):
    pico = max(range(24), key=lambda hora: medias[hora])
    intervalos = [Intervalo(f'{hora}h', f'{hora:02d}:00 às {hora:02d}:59', None, None) for hora in range(24)]
    subtitulo = f'Pico às {pico}h · média de 30 dias, horário de Brasília'
    return montar_grafico(subtitulo, intervalos, [round(valor) for valor in medias])


def _buscar_demografia(instagram, breakdown):
    """Devolve ([(chave, quantidade)], motivo). motivo explica quando o Instagram não entrega o dado."""
    try:
        resp = _consultar_demografia(instagram, breakdown)
        if not resp.ok and 'timeframe' in resp.text:
            resp = _consultar_demografia(instagram, breakdown, timeframe='this_month')
    except requests.RequestException:
        logger.warning('Falha de rede ao buscar público por %s', breakdown)
        return [], 'O Instagram não respondeu a tempo. Recarregue a página para tentar de novo.'

    if not resp.ok:
        logger.warning('Instagram recusou público por %s (HTTP %s): %s', breakdown, resp.status_code, resp.text[:300])
        return [], _motivo_erro_publico(resp)
    try:
        quebras = resp.json()['data'][0]['total_value']['breakdowns']
        resultados = quebras[0]['results'] if quebras else []
        itens = [(r['dimension_values'][0], r['value']) for r in resultados if r.get('value')]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        logger.warning('Resposta inesperada de público por %s: %s', breakdown, resp.text[:300])
        return [], 'O Instagram devolveu uma resposta em formato inesperado.'
    if not itens:
        return [], 'O Instagram ainda não tem dados suficientes sobre o seu público.'
    return itens, None


def _consultar_demografia(instagram, breakdown, timeframe=None):
    params = {
        'metric': 'follower_demographics',
        'period': 'lifetime',
        'metric_type': 'total_value',
        'breakdown': breakdown,
        'access_token': instagram.access_token,
    }
    if timeframe:
        params['timeframe'] = timeframe
    return requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/insights', params=params, timeout=10)


def _buscar_horarios_ativos(instagram):
    """Devolve (média de seguidores online por hora local [0..23], motivo)."""
    agora = timezone.now()
    try:
        resp = requests.get(f'{INSTAGRAM_GRAPH_URL}/{instagram.instagram_user_id}/insights', params={
            'metric': 'online_followers',
            'period': 'lifetime',
            'since': int((agora - timedelta(days=29)).timestamp()),
            'until': int(agora.timestamp()),
            'access_token': instagram.access_token,
        }, timeout=10)
    except requests.RequestException:
        logger.warning('Falha de rede ao buscar horários ativos')
        return None, 'O Instagram não respondeu a tempo. Recarregue a página para tentar de novo.'

    if not resp.ok:
        logger.warning('Instagram recusou horários ativos (HTTP %s): %s', resp.status_code, resp.text[:300])
        return None, _motivo_erro_publico(resp)
    try:
        dias = [item['value'] for item in resp.json()['data'][0]['values'] if item.get('value')]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        logger.warning('Resposta inesperada de horários ativos: %s', resp.text[:300])
        return None, 'O Instagram devolveu uma resposta em formato inesperado.'
    if not dias:
        return None, 'O Instagram ainda não tem dados de horários de atividade.'
    return _medias_por_hora_local(dias, agora), None


def _medias_por_hora_local(dias, referencia):
    deslocamento = _horas_entre_fusos(referencia)
    somas, contagens = [0] * 24, [0] * 24
    for dia in dias:
        for hora_instagram, valor in dia.items():
            hora_local = (int(hora_instagram) + deslocamento) % 24
            somas[hora_local] += valor or 0
            contagens[hora_local] += 1
    return [somas[h] / contagens[h] if contagens[h] else 0 for h in range(24)]


def _horas_entre_fusos(referencia):
    local = timezone.localtime(referencia).utcoffset()
    instagram = referencia.astimezone(FUSO_DO_INSTAGRAM).utcoffset()
    return int((local - instagram).total_seconds() // 3600)


def _motivo_erro_publico(resp):
    try:
        erro = resp.json().get('error') or {}
    except (ValueError, AttributeError):
        erro = {}
    if not isinstance(erro, dict):
        erro = {}
    codigo = erro.get('code')
    mensagem = erro.get('message') or ''

    if codigo in (10, 200) or 'permission' in mensagem.lower():
        return ('A permissão de estatísticas não foi concedida. '
                'Desconecte e conecte o Instagram de novo aceitando todas as permissões.')
    if codigo == 190:
        return 'A conexão com o Instagram expirou. Desconecte e conecte de novo.'
    if '100' in mensagem and 'follower' in mensagem.lower():
        return 'O Instagram só libera dados de público para contas com pelo menos 100 seguidores.'
    return f'O Instagram não informou este dado: {mensagem or f"HTTP {resp.status_code}"}'
