import getpass

from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Perfil


class Command(BaseCommand):
    help = (
        'Cria um painel novo e independente: um login administrador com Instagram, programação, '
        'tarefas e usuários próprios, sem acesso aos dados dos outros painéis.'
    )

    def add_arguments(self, parser):
        parser.add_argument('usuario', help='Login do administrador do painel novo (ex.: mironlucas2)')

    def handle(self, *args, usuario, **opcoes):
        if User.objects.filter(username__iexact=usuario).exists():
            raise CommandError(f'Já existe um login "{usuario}". Escolha outro nome.')

        senha = self._pedir_senha(usuario)
        with transaction.atomic():
            admin = User.objects.create_user(username=usuario, password=senha)
            # Dono da própria conta: é isso que separa os dados deste painel dos demais.
            Perfil.objects.create(usuario=admin, conta=admin, papel=Perfil.ADMIN)
        self.stdout.write(self.style.SUCCESS(
            f'Painel criado. Entre com "{usuario}" para conectar o Instagram e cadastrar os usuários deste painel.'
        ))

    def _pedir_senha(self, usuario):
        while True:
            senha = getpass.getpass('Senha do painel novo: ')
            if senha != getpass.getpass('Repita a senha: '):
                self.stderr.write('As senhas não conferem. Tente de novo.')
                continue
            try:
                password_validation.validate_password(senha, User(username=usuario))
            except ValidationError as erro:
                self.stderr.write(' '.join(erro.messages))
                continue
            return senha
