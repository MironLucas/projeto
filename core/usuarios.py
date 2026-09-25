from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Perfil
from .permissoes import somente_admin

User = get_user_model()
PAPEIS_ATRIBUIVEIS = [(Perfil.EDITOR, 'Edição'), (Perfil.VISUALIZADOR, 'Visualização')]


class NovoUsuarioForm(forms.Form):
    nome = forms.CharField(label='Nome', max_length=150, required=False)
    usuario = forms.CharField(label='Usuário', max_length=150)
    senha = forms.CharField(label='Senha', widget=forms.PasswordInput)
    papel = forms.ChoiceField(label='Acesso', choices=PAPEIS_ATRIBUIVEIS, initial=Perfil.EDITOR)

    def clean_usuario(self):
        usuario = self.cleaned_data['usuario'].strip()
        User.username_validator(usuario)
        if User.objects.filter(username__iexact=usuario).exists():
            raise ValidationError('Já existe um usuário com esse nome.')
        return usuario

    def clean(self):
        dados = super().clean()
        if dados.get('usuario') and dados.get('senha'):
            try:
                validate_password(dados['senha'], User(username=dados['usuario'], first_name=dados.get('nome', '')))
            except ValidationError as erro:
                self.add_error('senha', erro)
        return dados


@login_required
@somente_admin
def usuarios(request):
    form = NovoUsuarioForm()
    if request.method == 'POST':
        form = NovoUsuarioForm(request.POST)
        if form.is_valid():
            dados = form.cleaned_data
            with transaction.atomic():
                novo = User.objects.create_user(username=dados['usuario'], password=dados['senha'], first_name=dados['nome'])
                Perfil.objects.create(usuario=novo, conta=request.conta, papel=dados['papel'])
            messages.success(request, f'Usuário {novo.username} criado.')
            return redirect('usuarios')

    membros = Perfil.objects.filter(conta=request.conta).select_related('usuario').order_by('usuario__date_joined')
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
    nome = perfil.usuario.username
    perfil.usuario.delete()
    messages.success(request, f'Usuário {nome} excluído.')
    return redirect('usuarios')


def _membro_editavel(request, perfil_id):
    # O administrador não se edita nem se exclui por aqui, e só mexe em membros da própria conta.
    return get_object_or_404(
        Perfil.objects.select_related('usuario').exclude(papel=Perfil.ADMIN),
        id=perfil_id, conta=request.conta,
    )
