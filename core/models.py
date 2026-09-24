from django.conf import settings
from django.db import models


class InstagramConnection(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instagram_connection',
    )
    instagram_user_id = models.CharField(max_length=64, blank=True)
    instagram_username = models.CharField(max_length=150, blank=True)
    account_type = models.CharField(max_length=32, blank=True)
    access_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'@{self.instagram_username}' if self.instagram_username else f'Conexão de {self.user}'


class SeguidoresDia(models.Model):
    # Ligado ao id da conta do Instagram (e não à conexão) para o histórico sobreviver a reconexões.
    instagram_user_id = models.CharField(max_length=64)
    data = models.DateField()
    novos_seguidores = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['instagram_user_id', 'data'], name='seguidores_dia_unico'),
        ]

    def __str__(self):
        return f'{self.instagram_user_id} {self.data}: {self.novos_seguidores}'
