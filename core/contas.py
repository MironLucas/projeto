"""Várias contas do Instagram por pessoa: trocar a conta aberta e desconectar uma delas."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import InstagramConnection, Perfil
from .permissoes import abrir_conta


@require_POST
@login_required
def usar_conta(request, conta_id):
    get_object_or_404(Perfil, usuario=request.user, conta_id=conta_id)
    abrir_conta(request, conta_id)
    return _voltar(request)


@require_POST
@login_required
def desconectar_conta(request, conta_id):
    # Só quem administra a conta desconecta o Instagram dela (mesmo que a conta aberta agora seja outra).
    perfil = get_object_or_404(Perfil, usuario=request.user, conta_id=conta_id, papel=Perfil.ADMIN)
    conexao = InstagramConnection.objects.filter(user=perfil.conta).first()
    if conexao:
        conexao.desconectar()
        messages.info(request, f'@{conexao.instagram_username} foi desconectada e saiu da sua lista de contas.')
    return _voltar(request)


def _voltar(request):
    origem = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(origem, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(origem)
    return redirect('dashboard')
