import re

from django.http import HttpResponse


def responder_arquivo(request, dados, tipo):
    """Entrega uma mídia guardada no banco, aceitando pedidos por partes (Range)."""
    total = len(dados)
    inicio, fim, status = 0, total - 1, 200

    # Suporte a Range: o Safari (iPhone) só toca vídeo se o servidor aceitar pedidos por partes.
    faixa = re.fullmatch(r'bytes=(\d*)-(\d*)', request.headers.get('Range', ''))
    if faixa and (faixa[1] or faixa[2]):
        if faixa[1]:
            inicio = int(faixa[1])
            fim = min(int(faixa[2]), total - 1) if faixa[2] else total - 1
        else:
            inicio = max(0, total - int(faixa[2]))
        if inicio > fim:
            resposta = HttpResponse(status=416)
            resposta['Content-Range'] = f'bytes */{total}'
            return resposta
        status = 206

    resposta = HttpResponse(dados[inicio:fim + 1], status=status, content_type=tipo)
    resposta['Accept-Ranges'] = 'bytes'
    resposta['Content-Length'] = str(fim - inicio + 1)
    resposta['Content-Disposition'] = 'inline'
    resposta['Cache-Control'] = 'private, max-age=86400'
    if status == 206:
        resposta['Content-Range'] = f'bytes {inicio}-{fim}/{total}'
    return resposta
