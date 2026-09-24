from django import template

register = template.Library()

UNIDADES = [(1_000, 'mil'), (1_000_000, 'mi'), (1_000_000_000, 'bi')]


@register.filter
def compacto(valor):
    """Número curto no estilo do Instagram: 1523 -> '1,5 mil', 12345 -> '12 mil'."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return valor
    sinal, numero = ('-' if numero < 0 else ''), abs(numero)
    if numero < 1000:
        return f'{sinal}{numero}'

    for limite, sufixo in UNIDADES:
        reduzido = numero / limite
        casas = 1 if reduzido < 10 else 0
        arredondado = round(reduzido, casas)
        if arredondado < 1000 or sufixo == UNIDADES[-1][1]:
            break
    if casas and arredondado != int(arredondado):
        texto = f'{arredondado:.1f}'.replace('.', ',')
    else:
        texto = str(int(arredondado))
    return f'{sinal}{texto} {sufixo}'
