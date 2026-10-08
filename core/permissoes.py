import logging
from functools import wraps
from urllib.parse import quote

from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse
from django.utils.functional import SimpleLazyObject
from django.utils.http import url_has_allowed_host_and_scheme

from .models import InstagramConnection, Perfil

logger = logging.getLogger(__name__)

METODOS_DE_LEITURA = {'GET', 'HEAD', 'OPTIONS'}
CHAVE_CONTA_ATUAL = 'conta_atual'
# Trocar de conta e desconectar valem mesmo para quem só visualiza a conta aberta: a própria view
# confere o acesso à conta de destino. Comentar nos itens da programação também: é como o cliente pede ajustes.
LIBERADAS_PARA_QUEM_VISUALIZA = {'login', 'logout', 'usar_conta', 'desconectar_conta',
                                 'agenda_comentarios', 'agenda_excluir_comentario', 'notificacoes_lidas',
                                 'meu_perfil', 'esqueci_senha', 'nova_senha'}


class PerfilMiddleware:
    """Define request.conta (dono dos dados), request.perfil (acesso a ela) e request.perfis (todas as contas
    da pessoa), e bloqueia alterações de quem só visualiza a conta aberta."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.perfil = None
        request.conta = None
        request.perfis = []
        request.conexoes = {}
        if request.user.is_authenticated:
            request.perfis = perfis_de(request.user)
            request.conexoes = {c.user_id: c for c in
                                InstagramConnection.objects.filter(user__in=[p.conta_id for p in request.perfis])}
            request.perfil = _conta_aberta(request, request.perfis, request.conexoes)
            request.conta = request.perfil.conta
            if request.method not in METODOS_DE_LEITURA and not request.perfil.pode_editar \
                    and _nome_da_rota(request) not in LIBERADAS_PARA_QUEM_VISUALIZA:
                return _somente_visualizacao(request)
        return self.get_response(request)


def perfis_de(usuario):
    """Contas que a pessoa acessa, começando pela própria."""
    perfis = sorted(Perfil.objects.filter(usuario=usuario).select_related('conta'),
                    key=lambda perfil: (perfil.conta_id != usuario.id, perfil.id))
    if not perfis:
        # Usuários criados fora da tela Usuários (ex.: createsuperuser) administram a própria conta.
        perfis = [Perfil.objects.create(usuario=usuario, conta=usuario, papel=Perfil.ADMIN)]
    return perfis


def abrir_conta(request, conta_id):
    request.session[CHAVE_CONTA_ATUAL] = conta_id


def _conta_aberta(request, perfis, conexoes):
    escolhida = request.session.get(CHAVE_CONTA_ATUAL)
    perfil = next((perfil for perfil in perfis if perfil.conta_id == escolhida), None)
    if perfil and (perfil.conta_id in conexoes or not conexoes):
        return perfil
    # Sem escolha, ou a conta escolhida foi desconectada: abre a primeira que tem Instagram.
    return next((perfil for perfil in perfis if perfil.conta_id in conexoes), perfil or perfis[0])


def _nome_da_rota(request):
    try:
        return resolve(request.path_info).url_name
    except Resolver404:
        return None


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
        'conta_atual_menu': _conta_para_o_menu(request, perfil) if perfil else None,
        # Só consulta o banco se a página mostrar o sininho.
        'notificacoes_total': SimpleLazyObject(lambda: _total_de_notificacoes(request)),
        # Contas desconectadas saem da lista; os dados delas ficam guardados para quando voltarem.
        'contas_da_pessoa': [_conta_para_o_menu(request, p) for p in getattr(request, 'perfis', [])
                             if p.conta_id in getattr(request, 'conexoes', {})],
    }


def _total_de_notificacoes(request):
    if not getattr(request, 'perfis', None):
        return 0
    from .notificacoes import total_nao_lidos  # notificacoes usa este módulo
    return total_nao_lidos(request)


def _conta_para_o_menu(request, perfil):
    """Uma conta no menu da foto: nome, foto salva e se a pessoa administra."""
    conexao = request.conexoes.get(perfil.conta_id)
    if conexao and conexao.instagram_username:
        nome = f'@{conexao.instagram_username}'
    elif perfil.conta.first_name.startswith('@'):
        nome = perfil.conta.first_name  # conta adicionada que foi desconectada
    else:
        nome = 'Sem Instagram conectado'
    return {
        'id': perfil.conta_id,
        'nome': nome,
        'foto': conexao.perfil_foto if conexao else '',
        'conectada': conexao is not None,
        'atual': perfil.conta_id == request.conta.id,
        'e_admin': perfil.e_admin,
    }


def falha_csrf(request, reason=''):
    """Página desatualizada (token CSRF antigo, comum ao voltar para uma aba aberta há tempo no celular).

    Em vez da tela crua de 403, manda a pessoa de volta para tentar de novo com um token novo.
    """
    logger.warning('Verificação CSRF recusada em %s: %s', request.path, reason)
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'erro': 'A página estava desatualizada. Recarregue e tente de novo.'}, status=403)
    if request.path == reverse('login'):
        if request.user.is_authenticated:
            return redirect('dashboard')
        destino = f"{reverse('login')}?expirou=1"
        proxima = request.POST.get('next', '')
        if proxima and url_has_allowed_host_and_scheme(proxima, allowed_hosts={request.get_host()}):
            destino += f'&next={quote(proxima)}'
        return redirect(destino)
    return _voltar(request, 'A página estava desatualizada e nada foi salvo. Tente de novo.')


def _somente_visualizacao(request):
    mensagem = 'Seu acesso é somente de visualização.'
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'erro': mensagem}, status=403)
    return _voltar(request, mensagem)


def _voltar(request, mensagem):
    messages.error(request, mensagem)
    origem = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(origem, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(origem)
    return redirect('dashboard')
