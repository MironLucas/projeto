"""Login sem diferenciar maiúsculas de minúsculas no usuário: "MironLucas" entra como "mironlucas"."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class UsuarioSemMaiusculasBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None
        usuario = self._achar(username.strip())
        if usuario is None:
            # Mesmo custo de quando o usuário existe, para não revelar quais nomes estão cadastrados.
            get_user_model()().set_password(password)
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None

    @staticmethod
    def _achar(nome):
        candidatos = list(get_user_model()._default_manager.filter(username__iexact=nome)[:2])
        if len(candidatos) == 1:
            return candidatos[0]
        # Se existirem dois usuários que só diferem nas maiúsculas, vale só o nome digitado exatamente igual.
        return next((usuario for usuario in candidatos if usuario.username == nome), None)
