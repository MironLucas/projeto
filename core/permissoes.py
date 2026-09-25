from functools import wraps

from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Perfil

METODOS_DE_LEITURA = {'GET', 'HEAD', 'OPTIONS'}


class PerfilMiddleware:
    """Define request.conta (dono dos dados) e request.perfil, e bloqueia alterações de quem só visualiza."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.perfil = None
        request.conta = None
        if request.user.is_authenticated:
            request.perfil = perfil_de(request.user)
            request.conta = request.perfil.conta
            liberado = request.path in (reverse('login'), reverse('logout'))
            if request.method not in METODOS_DE_LEITURA and not request.perfil.pode_editar and not liberado:
                return _somente_visualizacao(request)
        return self.get_response(request)


def perfil_de(usuario):
    try:
        return usuario.perfil
    except Perfil.DoesNotExist:
        # Usuários criados fora da tela Usuários (ex.: createsuperuser) administram a própria conta.
        return Perfil.objects.create(usuario=usuario, conta=usuario, papel=Perfil.ADMIN)


def somente_admin(view):
    @wraps(view)
    def verificar(request, *args, **kwargs):
        if not (request.perfil and request.perfil.e_admin):
            return HttpResponseForbidden('Apenas o administrador pode acessar esta página.')
        return view(request, *args, **kwargs)
    return verificar


def contexto_de_permissoes(request):
    perfil = getattr(request, 'perfil', None)
    return {
        'perfil_atual': perfil,
        'pode_editar': bool(perfil and perfil.pode_editar),
        'e_admin': bool(perfil and perfil.e_admin),
    }


def _somente_visualizacao(request):
    mensagem = 'Seu acesso é somente de visualização.'
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'erro': mensagem}, status=403)
    messages.error(request, mensagem)
    origem = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(origem, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(origem)
    return redirect('dashboard')
