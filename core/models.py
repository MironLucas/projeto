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


class ItemAgenda(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='itens_agenda')
    data = models.DateField()
    horario = models.TimeField(null=True, blank=True)
    titulo = models.CharField(max_length=200)
    concluido = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [models.F('horario').asc(nulls_last=True), 'criado_em']

    def __str__(self):
        return f'{self.data} {self.titulo}'


class ListaTarefas(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='listas_tarefas')
    titulo = models.CharField(max_length=80)
    posicao = models.PositiveIntegerField(default=0)
    cor = models.CharField(max_length=7, default='#7c5cff')

    class Meta:
        ordering = ['posicao', 'id']

    def __str__(self):
        return self.titulo


class Cartao(models.Model):
    lista = models.ForeignKey(ListaTarefas, on_delete=models.CASCADE, related_name='cartoes')
    titulo = models.CharField(max_length=300)
    legenda = models.TextField(blank=True)
    posicao = models.PositiveIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    # Metadados da mídia ficam aqui; os bytes ficam em ArquivoCartao para o quadro não carregá-los.
    midia_tipo = models.CharField(max_length=50, blank=True)
    midia_nome = models.CharField(max_length=255, blank=True)
    midia_tamanho = models.PositiveIntegerField(default=0)
    midia_versao = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['posicao', 'id']

    def __str__(self):
        return self.titulo

    @property
    def e_imagem(self):
        return self.midia_tipo.startswith('image/')

    @property
    def e_video(self):
        return self.midia_tipo.startswith('video/')


class ArquivoCartao(models.Model):
    # Guardado no banco porque o disco do Render gratuito é apagado a cada deploy.
    cartao = models.OneToOneField(Cartao, on_delete=models.CASCADE, primary_key=True, related_name='arquivo')
    conteudo = models.BinaryField()


class Perfil(models.Model):
    ADMIN = 'admin'
    EDITOR = 'editor'
    VISUALIZADOR = 'visualizador'
    PAPEIS = [
        (ADMIN, 'Administrador'),
        (EDITOR, 'Edição'),
        (VISUALIZADOR, 'Visualização'),
    ]

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    # Dono dos dados que este usuário acessa: o Instagram, a programação e as tarefas são dessa conta.
    conta = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membros')
    papel = models.CharField(max_length=20, choices=PAPEIS, default=VISUALIZADOR)

    def __str__(self):
        return f'{self.usuario} ({self.get_papel_display()})'

    @property
    def e_admin(self):
        return self.papel == self.ADMIN

    @property
    def pode_editar(self):
        return self.papel in (self.ADMIN, self.EDITOR)
