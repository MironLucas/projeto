import os
import re

from django.http import HttpResponse, StreamingHttpResponse

TAMANHO_DO_BLOCO = 512 * 1024


def responder_arquivo(request, dados, tipo):
    """Entrega uma mídia guardada no banco, aceitando pedidos por partes (Range)."""
    faixa = _faixa_pedida(request, len(dados))
    if faixa is None:
        return _fora_da_faixa(len(dados))
    inicio, fim, status = faixa
    resposta = HttpResponse(dados[inicio:fim + 1], status=status, content_type=tipo)
    return _cabecalhos(resposta, inicio, fim, len(dados), status)


def responder_arquivo_em_disco(request, caminho, tipo):
    """Entrega um arquivo do disco em blocos, sem carregar o vídeo inteiro na memória."""
    total = os.path.getsize(caminho)
    faixa = _faixa_pedida(request, total)
    if faixa is None:
        return _fora_da_faixa(total)
    inicio, fim, status = faixa
    resposta = StreamingHttpResponse(_ler_em_blocos(caminho, inicio, fim - inicio + 1), status=status, content_type=tipo)
    return _cabecalhos(resposta, inicio, fim, total, status)


def _ler_em_blocos(caminho, inicio, quantidade):
    with open(caminho, 'rb') as arquivo:
        arquivo.seek(inicio)
        while quantidade > 0:
            bloco = arquivo.read(min(TAMANHO_DO_BLOCO, quantidade))
            if not bloco:
                break
            quantidade -= len(bloco)
            yield bloco


def _faixa_pedida(request, total):
    """(início, fim, status) do pedido; None se a faixa pedida não existe no arquivo."""
    # Suporte a Range: o Safari (iPhone) só toca vídeo se o servidor aceitar pedidos por partes.
    faixa = re.fullmatch(r'bytes=(\d*)-(\d*)', request.headers.get('Range', ''))
    if not faixa or not (faixa[1] or faixa[2]):
        return 0, total - 1, 200
    if faixa[1]:
        inicio = int(faixa[1])
        fim = min(int(faixa[2]), total - 1) if faixa[2] else total - 1
    else:
        inicio, fim = max(0, total - int(faixa[2])), total - 1
    if inicio > fim:
        return None
    return inicio, fim, 206


def _fora_da_faixa(total):
    resposta = HttpResponse(status=416)
    resposta['Content-Range'] = f'bytes */{total}'
    return resposta


def _cabecalhos(resposta, inicio, fim, total, status):
    resposta['Accept-Ranges'] = 'bytes'
    resposta['Content-Length'] = str(fim - inicio + 1)
    resposta['Content-Disposition'] = 'inline'
    resposta['Cache-Control'] = 'private, max-age=86400'
    if status == 206:
        resposta['Content-Range'] = f'bytes {inicio}-{fim}/{total}'
    return resposta
