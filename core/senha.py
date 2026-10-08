"""Esqueci minha senha (link por e-mail) e "Meu perfil", onde cada pessoa cuida do próprio nome, e-mail e senha."""
import logging

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

logger = logging.getLogger(__name__)
User = get_user_model()

PEDIDOS_POR_IP = 5
JANELA_DE_PEDIDOS = 15 * 60  # segundos


def email_em_uso(email, exceto=None):
    """Cada e-mail fica com uma pessoa só, para o link de nova senha ir para quem é dono dele."""
    outros = User.objects.filter(email__iexact=email, is_active=True)
    if exceto is not None:
        outros = outros.exclude(pk=exceto.pk)
    return outros.exists()


class EsqueciSenhaForm(PasswordResetForm):
    email = forms.CharField(label='Usuário ou e-mail', max_length=254)

    def get_users(self, identificacao):
        identificacao = identificacao.strip()
        if not identificacao:
            return []
        pessoas = User._default_manager.filter(
            Q(username__iexact=identificacao) | Q(email__iexact=identificacao), is_active=True,
        ).exclude(email='')
        return [pessoa for pessoa in pessoas if pessoa.has_usable_password()]


class NovaSenhaForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].label = 'Nova senha'
        self.fields['new_password2'].label = 'Repita a nova senha'


class EsqueciSenhaView(auth_views.PasswordResetView):
    form_class = EsqueciSenhaForm
    template_name = 'core/esqueci_senha.html'
    email_template_name = 'core/email/nova_senha.txt'
    html_email_template_name = 'core/email/nova_senha.html'
    subject_template_name = 'core/email/nova_senha_assunto.txt'
    success_url = reverse_lazy('esqueci_senha_enviado')

    def form_valid(self, form):
        # A resposta é sempre a mesma (existindo ou não a pessoa), para ninguém descobrir quem tem cadastro.
        ip = self.request.META.get('HTTP_X_FORWARDED_FOR', self.request.META.get('REMOTE_ADDR', '')).split(',')[0]
        chave = f'esqueci-senha:{ip}'
        pedidos = cache.get(chave, 0)
        if pedidos >= PEDIDOS_POR_IP:
            logger.warning('Esqueci minha senha: limite de pedidos atingido para %s', ip)
            return redirect(self.success_url)
        cache.set(chave, pedidos + 1, JANELA_DE_PEDIDOS)
        try:
            return super().form_valid(form)
        except Exception:  # falha no servidor de e-mail: registra para o administrador, sem expor nada
            logger.exception('Esqueci minha senha: não foi possível enviar o e-mail')
            return redirect(self.success_url)


class NovaSenhaView(auth_views.PasswordResetConfirmView):
    form_class = NovaSenhaForm
    template_name = 'core/nova_senha.html'
    success_url = reverse_lazy('nova_senha_pronta')


class MeusDadosForm(forms.Form):
    nome = forms.CharField(label='Nome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=False)

    def __init__(self, *args, pessoa, **kwargs):
        super().__init__(*args, **kwargs)
        self.pessoa = pessoa

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if email and email_em_uso(email, exceto=self.pessoa):
            raise ValidationError('Esse e-mail já está em outro usuário.')
        return email


class TrocarSenhaForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = 'Senha atual'
        self.fields['new_password1'].label = 'Nova senha'
        self.fields['new_password2'].label = 'Repita a nova senha'
        self.fields['old_password'].widget.attrs.pop('autofocus', None)


@login_required
def meu_perfil(request):
    pessoa = request.user
    dados = MeusDadosForm(initial={'nome': pessoa.first_name, 'email': pessoa.email}, pessoa=pessoa)
    senha = TrocarSenhaForm(pessoa)
    if request.method == 'POST' and request.POST.get('acao') == 'dados':
        dados = MeusDadosForm(request.POST, pessoa=pessoa)
        if dados.is_valid():
            pessoa.first_name = dados.cleaned_data['nome'].strip()
            pessoa.email = dados.cleaned_data['email']
            pessoa.save(update_fields=['first_name', 'email'])
            messages.success(request, 'Seus dados foram salvos.')
            return redirect('meu_perfil')
    elif request.method == 'POST' and request.POST.get('acao') == 'senha':
        senha = TrocarSenhaForm(pessoa, request.POST)
        if senha.is_valid():
            senha.save()
            update_session_auth_hash(request, senha.user)  # continua logado aqui; sai dos outros aparelhos
            messages.success(request, 'Senha alterada.')
            return redirect('meu_perfil')
    return render(request, 'core/meu_perfil.html', {
        'active_menu': 'perfil',
        'dados': dados,
        'senha': senha,
    })
