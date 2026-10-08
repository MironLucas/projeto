from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Envia um e-mail de teste para conferir se a configuração de e-mail (.env) está funcionando.'

    def add_arguments(self, parser):
        parser.add_argument('destino', help='E-mail que vai receber o teste')

    def handle(self, *args, destino, **opcoes):
        if not settings.EMAIL_HOST:
            raise CommandError('EMAIL_HOST não está no .env: os e-mails não estão sendo enviados de verdade.')
        self.stdout.write(f'Enviando por {settings.EMAIL_HOST}:{settings.EMAIL_PORT} como {settings.EMAIL_HOST_USER}...')
        try:
            send_mail(
                'Teste de e-mail do Hopkins',
                'Se você recebeu este e-mail, o envio do Hopkins está funcionando (inclusive o "Esqueci minha senha").',
                settings.DEFAULT_FROM_EMAIL, [destino],
            )
        except Exception as erro:
            raise CommandError(f'Não foi possível enviar: {erro}')
        self.stdout.write(self.style.SUCCESS(f'Enviado para {destino}. Confira a caixa de entrada (e o spam).'))
