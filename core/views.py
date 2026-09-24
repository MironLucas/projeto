from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import InstagramConnection


@login_required
def dashboard(request):
    instagram = InstagramConnection.objects.filter(user=request.user).first()
    return render(request, 'core/dashboard.html', {
        'active_menu': 'dashboard',
        'instagram': instagram,
    })


@login_required
def programacao(request):
    return render(request, 'core/programacao.html', {'active_menu': 'programacao'})


@login_required
def tarefas(request):
    return render(request, 'core/tarefas.html', {'active_menu': 'tarefas'})


@login_required
def instagram_conectar(request):
    # A integração real com a API do Instagram depende das credenciais do
    # app (Client ID/Secret) para o fluxo OAuth. Enquanto isso, avisamos o
    # usuário para que a interface já fique pronta para quando isso existir.
    messages.info(
        request,
        'Para concluir a conexão com o Instagram, configure as credenciais '
        'do app na Meta for Developers. A tela já está pronta para o fluxo.',
    )
    return redirect('dashboard')
