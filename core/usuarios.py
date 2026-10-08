from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Perfil
from .permissoes import somente_admin

User = get_user_model()
PAPEIS_ATRIBUIVEIS = [(Perfil.EDITOR, 'Edição'), (Perfil.VISUALIZADOR, 'Visualização')]


class NovoUsuarioForm(forms.Form):
    nome = forms.CharField(label='Nome', max_length=150, required=False)
    usuario = forms.CharField(label='Usuário', max_length=150)
    senha = forms.CharField(label='Senha', widget=forms.PasswordInput, required=False)
    papel = forms.ChoiceField(label='Acesso', choices=PAPEIS_ATRIBUIVEIS, initial=Perfil.EDITOR)

    def __init__(self, *args, conta, **kwargs):
        super().__init__(*args, **kwargs)
        self.conta = conta
        self.existente = None

    def clean_usuario(self):
        usuario = self.cleaned_data['usuario'].strip()
        User.username_validator(usuario)
        # Quem já tem login no Hopkins é convidado para esta conta e continua com a senha que já usa.
        self.existente = User.objects.filter(username__iexact=usuario, is_active=True).first()
        if self.existente and Perfil.objects.filter(usuario=self.existente, conta=self.conta).exists():
            raise ValidationError('Essa pessoa já tem acesso a esta conta.')
        if not self.existente and User.objects.filter(username__iexact=usuario).exists():
            raise ValidationError('Esse nome de usuário não está disponível.')
        return usuario

    def clean(self):
        dados = super().clean()
        if dados.get('usuario') and not self.existente:
            if not dados.get('senha'):
                self.add_error('senha', 'Informe uma senha.')
            else:
                try:
                    validate_password(dados['senha'], User(username=dados['usuario'], first_name=dados.get('nome', '')))
                except ValidationError as erro:
                    self.add_error('senha', erro)
        return dados


@login_required
@somente_admin
def usuarios(request):
    form = NovoUsuarioForm(conta=request.conta)
    if request.method == 'POST':
        form = NovoUsuarioForm(request.POST, conta=request.conta)
        if form.is_valid():
            dados = form.cleaned_data
            if form.existente:
                Perfil.objects.create(usuario=form.existente, conta=request.conta, papel=dados['papel'])
                messages.success(request, f'{form.existente.username} já tinha login e agora também acessa esta conta, '
                                          'com a senha que já usa.')
            else:
                with transaction.atomic():
                    novo = User.objects.create_user(username=dados['usuario'], password=dados['senha'], first_name=dados['nome'])
                    Perfil.objects.create(usuario=novo, conta=request.conta, papel=dados['papel'])
                messages.success(request, f'Usuário {novo.username} criado.')
            return redirect('usuarios')

    membros = (Perfil.objects.filter(conta=request.conta).select_related('usuario')
               .annotate(contas_da_pessoa=Count('usuario__perfis')).order_by('usuario__date_joined'))
    return render(request, 'core/usuarios.html', {
        'active_menu': 'usuarios',
        'form': form,
        'membros': membros,
        'papeis_atribuiveis': PAPEIS_ATRIBUIVEIS,
    })


@require_POST
@login_required
@somente_admin
def editar_usuario(request, perfil_id):
    perfil = _membro_editavel(request, perfil_id)
    papel = request.POST.get('papel')
    if papel in dict(PAPEIS_ATRIBUIVEIS):
        perfil.papel = papel
        perfil.save(update_fields=['papel'])

    usuario = perfil.usuario
    if _acessa_outras_contas(perfil):
        # Nome e senha são da pessoa, não desta conta: quem a convidou só muda o acesso dela aqui.
        messages.success(request, f'Acesso de {usuario.username} atualizado.')
        return redirect('usuarios')

    usuario.first_name = request.POST.get('nome', '').strip()[:150]
    nova_senha = request.POST.get('senha', '')
    if nova_senha:
        try:
            validate_password(nova_senha, usuario)
        except ValidationError as erro:
            messages.error(request, 'Senha não alterada: ' + ' '.join(erro.messages))
            usuario.save(update_fields=['first_name'])
            return redirect('usuarios')
        usuario.set_password(nova_senha)
    usuario.save()
    messages.success(request, f'Usuário {usuario.username} atualizado.')
    return redirect('usuarios')


@require_POST
@login_required
@somente_admin
def excluir_usuario(request, perfil_id):
    perfil = _membro_editavel(request, perfil_id)
    usuario = perfil.usuario
    with transaction.atomic():
        perfil.delete()
        # Tira o acesso a esta conta; o login só some se a pessoa não tiver acesso a mais nenhuma.
        if not usuario.perfis.exists():
            usuario.delete()
    messages.success(request, f'Usuário {usuario.username} removido desta conta.')
    return redirect('usuarios')


def _acessa_outras_contas(perfil):
    return Perfil.objects.filter(usuario_id=perfil.usuario_id).exclude(id=perfil.id).exists()


def _membro_editavel(request, perfil_id):
    # O administrador não se edita nem se exclui por aqui, e só mexe em membros da própria conta.
    return get_object_or_404(
        Perfil.objects.select_related('usuario').exclude(papel=Perfil.ADMIN),
        id=perfil_id, conta=request.conta,
    )
