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
    access_token = models.CharField(max_length=255, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'@{self.instagram_username}' if self.instagram_username else f'Conexão de {self.user}'
