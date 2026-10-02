"""Minigráfico de linha dos cards do resumo: o período anterior (apagado) seguido do atual (na cor do card)."""
import math
from datetime import timedelta

PONTOS_POR_PERIODO = 7
LARGURA, ALTURA, MARGEM = 100, 40, 5  # unidades do viewBox do SVG


def dividir_em_baldes(inicio, fim, maximo=PONTOS_POR_PERIODO):
    """Divide os dias de inicio a fim (datas) em até `maximo` faixas seguidas de tamanho parecido."""
    dias = (fim - inicio).days + 1
    quantidade = min(maximo, dias)
    return [
        (inicio + timedelta(days=i * dias // quantidade), inicio + timedelta(days=(i + 1) * dias // quantidade - 1))
        for i in range(quantidade)
    ]


def descrever_balde(inicio, fim):
    if inicio == fim:
        return f'{inicio:%d/%m}'
    if (inicio.year, inicio.month) == (fim.year, fim.month):
        return f'{inicio:%d}–{fim:%d/%m}'
    return f'{inicio:%d/%m}–{fim:%d/%m}'


def montar_minigrafico(anteriores, atuais):
    """anteriores e atuais são listas de (descrição, valor).

    Faltando dado no período atual não há gráfico; no anterior (ex.: antes do histórico salvo
    começar) as faixas sem dado ficam de fora.
    """
    if not atuais or any(valor is None for _, valor in atuais):
        return None
    anteriores = [(descricao, valor) for descricao, valor in anteriores if valor is not None]
    pontos = [(descricao, valor, False) for descricao, valor in anteriores] + \
             [(descricao, valor, True) for descricao, valor in atuais]
    valores = [valor for _, valor, _ in pontos]

    quantidade = len(pontos)
    menor, maior = min(valores), max(valores)
    xs = [LARGURA * i / (quantidade - 1) if quantidade > 1 else LARGURA for i in range(quantidade)]
    ys = [_altura(valor, menor, maior) for valor in valores]
    curvas = curvas_monotonas(xs, ys)

    # A linha apagada vai até o primeiro ponto do período atual; dali em diante é a cor do card.
    # Com um ponto só no período atual (ex.: Hoje), a cor começa no último ponto do anterior.
    inicio_cor = len(anteriores)
    if len(atuais) == 1 and anteriores:
        inicio_cor -= 1
    linha_anterior = _caminho(xs, ys, curvas, 0, inicio_cor) if inicio_cor else ''
    linha_atual = _caminho(xs, ys, curvas, inicio_cor, quantidade - 1)
    area = ''
    if quantidade - 1 > inicio_cor:
        area = f'{linha_atual} L{xs[-1]:.2f},{ALTURA} L{xs[inicio_cor]:.2f},{ALTURA} Z'

    # Cada ponto tem uma faixa de passar o mouse centrada nele; lado a lado elas cobrem o gráfico todo.
    meio_passo = LARGURA / (quantidade - 1) / 2 if quantidade > 1 else LARGURA / 2
    return {
        'linha_anterior': linha_anterior,
        'linha_atual': linha_atual,
        'area': area,
        'final': {'x': xs[-1], 'y': ys[-1] / ALTURA * 100},
        'fatias': [{
            'descricao': descricao,
            'valor': valor,
            'atual': atual,
            'largura': min(LARGURA, x + meio_passo) - max(0.0, x - meio_passo),
            'x': x,
            'y': y / ALTURA * 100,
        } for (descricao, valor, atual), x, y in zip(pontos, xs, ys)],
    }


def _altura(valor, menor, maior):
    if maior == menor:
        return ALTURA / 2
    return ALTURA - MARGEM - (valor - menor) / (maior - menor) * (ALTURA - 2 * MARGEM)


def curvas_monotonas(xs, ys):
    """Segmentos cúbicos que passam por todos os pontos sem inventar picos (Fritsch–Carlson)."""
    quantidade = len(xs)
    if quantidade < 2:
        return []
    inclinacoes = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(quantidade - 1)]
    tangentes = [inclinacoes[0]] + [
        0 if inclinacoes[i - 1] * inclinacoes[i] <= 0 else (inclinacoes[i - 1] + inclinacoes[i]) / 2
        for i in range(1, quantidade - 1)
    ] + [inclinacoes[-1]]
    for i, inclinacao in enumerate(inclinacoes):
        if inclinacao == 0:
            tangentes[i] = tangentes[i + 1] = 0
            continue
        a, b = tangentes[i] / inclinacao, tangentes[i + 1] / inclinacao
        soma = a * a + b * b
        if soma > 9:
            fator = 3 / math.sqrt(soma)
            tangentes[i], tangentes[i + 1] = fator * a * inclinacao, fator * b * inclinacao

    curvas = []
    for i in range(quantidade - 1):
        passo = (xs[i + 1] - xs[i]) / 3
        curvas.append(
            f'C{xs[i] + passo:.2f},{ys[i] + tangentes[i] * passo:.2f} '
            f'{xs[i + 1] - passo:.2f},{ys[i + 1] - tangentes[i + 1] * passo:.2f} '
            f'{xs[i + 1]:.2f},{ys[i + 1]:.2f}'
        )
    return curvas


def _caminho(xs, ys, curvas, de, ate):
    return ' '.join([f'M{xs[de]:.2f},{ys[de]:.2f}'] + curvas[de:ate])
