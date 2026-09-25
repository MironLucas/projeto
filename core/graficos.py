import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

DIAS_SEMANA = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
MAX_ROTULOS_EIXO_X = 12
MAX_ROTULOS_EIXO_X_CELULAR = 6


@dataclass
class Intervalo:
    rotulo: str
    descricao: str
    inicio: date
    fim: date


def intervalos_do_grafico(chave, inicio_periodo, fim_periodo, hoje):
    """Devolve (subtítulo, intervalos) — cada intervalo vira uma barra."""
    if chave == 'semana':
        segunda = hoje - timedelta(days=hoje.weekday())
        return 'Últimas 8 semanas', [
            _semana(segunda - timedelta(weeks=i), hoje) for i in range(7, -1, -1)
        ]

    if chave == 'mes':
        return f'Meses de {hoje.year}', [
            _mes(hoje.year, mes, date(hoje.year, mes, 1), hoje) for mes in range(1, hoje.month + 1)
        ]

    if chave == 'periodo':
        fim = min(fim_periodo, hoje)
        dias = (fim - inicio_periodo).days + 1
        if dias <= 0:
            return 'Sem dias até hoje', []
        if dias <= 31:
            return 'Por dia', [_dia(inicio_periodo + timedelta(days=i)) for i in range(dias)]
        if dias <= 16 * 7:
            inicios = [inicio_periodo + timedelta(weeks=i) for i in range(math.ceil(dias / 7))]
            return 'Por semana', [_semana(d, fim) for d in inicios]
        intervalos = []
        ano, mes = inicio_periodo.year, inicio_periodo.month
        while date(ano, mes, 1) <= fim:
            intervalos.append(_mes(ano, mes, max(date(ano, mes, 1), inicio_periodo), fim, com_ano=True))
            ano, mes = (ano, mes + 1) if mes < 12 else (ano + 1, 1)
        return 'Por mês', intervalos

    return 'Últimos 7 dias', [_dia(hoje - timedelta(days=i)) for i in range(6, -1, -1)]


def _dia(dia):
    return Intervalo(f'{DIAS_SEMANA[dia.weekday()]} {dia.day:02d}', f'{DIAS_SEMANA[dia.weekday()]}, {dia:%d/%m}', dia, dia)


def _semana(inicio, limite):
    fim = min(inicio + timedelta(days=6), limite)
    return Intervalo(f'{inicio:%d/%m}', f'{inicio:%d/%m} a {fim:%d/%m}', inicio, fim)


def _mes(ano, mes, inicio, limite, com_ano=False):
    fim = min(date(ano, mes, calendar.monthrange(ano, mes)[1]), limite)
    rotulo = f'{MESES[mes - 1]}/{ano % 100:02d}' if com_ano else MESES[mes - 1]
    return Intervalo(rotulo, f'{MESES[mes - 1]}/{ano}', inicio, fim)


def escala(minimo, maximo, marcas=4):
    """Marcas do eixo Y em números redondos (1, 2 ou 5 × 10ⁿ) que cobrem [minimo, maximo]."""
    minimo, maximo = min(minimo, 0), max(maximo, 0)
    if minimo == maximo:
        maximo = 1
    bruto = (maximo - minimo) / marcas
    magnitude = 10 ** math.floor(math.log10(bruto))
    passo = next(m * magnitude for m in (1, 2, 5, 10) if bruto <= m * magnitude)
    passo = max(1, int(round(passo)))
    inferior = math.floor(minimo / passo) * passo
    superior = math.ceil(maximo / passo) * passo
    return list(range(inferior, superior + passo, passo))


def montar_grafico(subtitulo, intervalos, valores, parciais=None):
    parciais = parciais or [False] * len(intervalos)
    existentes = [v for v in valores if v is not None]
    if not existentes:
        return {'subtitulo': subtitulo, 'vazio': True, 'barras': [], 'marcas': []}

    marcas = escala(min(existentes), max(existentes))
    inferior, superior = marcas[0], marcas[-1]
    faixa = superior - inferior
    base = (0 - inferior) / faixa * 100
    passo_rotulo = max(1, math.ceil(len(intervalos) / MAX_ROTULOS_EIXO_X))
    passo_rotulo_celular = max(1, math.ceil(len(intervalos) / MAX_ROTULOS_EIXO_X_CELULAR))

    barras = []
    for indice, (intervalo, valor, parcial) in enumerate(zip(intervalos, valores, parciais)):
        barra = {
            'rotulo': intervalo.rotulo,
            'descricao': intervalo.descricao,
            'valor': valor,
            'parcial': parcial,
            'mostrar_rotulo': indice % passo_rotulo == 0,
            'rotulo_no_celular': indice % passo_rotulo_celular == 0,
        }
        if valor is not None:
            altura = abs(valor) / faixa * 100
            barra['altura'] = round(altura, 2)
            barra['inferior'] = round(base if valor >= 0 else base - altura, 2)
            barra['negativo'] = valor < 0
        barras.append(barra)

    return {
        'subtitulo': subtitulo,
        'vazio': False,
        'barras': barras,
        'base': round(base, 2),
        'marcas': [{'valor': m, 'posicao': round((m - inferior) / faixa * 100, 2)} for m in marcas],
    }
