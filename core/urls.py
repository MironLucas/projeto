from django.contrib.auth import views as auth_views
from django.urls import path

from . import agenda, comentarios, contas, meta, publico, quadro, usuarios, views

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='core/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/dados/', views.dashboard_dados, name='dashboard_dados'),
    path('publico/', publico.publico, name='publico'),
    path('publico/dados/', publico.publico_dados, name='publico_dados'),

    path('programacao/', agenda.programacao, name='programacao'),
    path('programacao/itens/', agenda.adicionar_item, name='agenda_adicionar'),
    path('programacao/itens/<int:item_id>/editar/', agenda.editar_item, name='agenda_editar'),
    path('programacao/midias/<int:midia_id>/', agenda.midia_item, name='agenda_midia'),
    path('programacao/itens/<int:item_id>/concluir/', agenda.alternar_item, name='agenda_alternar'),
    path('programacao/itens/<int:item_id>/excluir/', agenda.excluir_item, name='agenda_excluir'),
    path('programacao/itens/<int:item_id>/comentarios/', comentarios.comentarios_item, name='agenda_comentarios'),
    path('programacao/comentarios/<int:comentario_id>/excluir/', comentarios.excluir_comentario,
         name='agenda_excluir_comentario'),

    path('tarefas/', quadro.tarefas, name='tarefas'),
    path('tarefas/listas/', quadro.criar_lista, name='quadro_criar_lista'),
    path('tarefas/listas/<int:lista_id>/editar/', quadro.editar_lista, name='quadro_editar_lista'),
    path('tarefas/listas/<int:lista_id>/mover/', quadro.mover_lista, name='quadro_mover_lista'),
    path('tarefas/listas/<int:lista_id>/excluir/', quadro.excluir_lista, name='quadro_excluir_lista'),
    path('tarefas/listas/<int:lista_id>/cartoes/', quadro.criar_cartao, name='quadro_criar_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/editar/', quadro.editar_cartao, name='quadro_editar_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/arquivo/', quadro.arquivo_cartao, name='quadro_arquivo_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/mover/', quadro.mover_cartao, name='quadro_mover_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/excluir/', quadro.excluir_cartao, name='quadro_excluir_cartao'),

    path('usuarios/', usuarios.usuarios, name='usuarios'),
    path('usuarios/<int:perfil_id>/editar/', usuarios.editar_usuario, name='usuarios_editar'),
    path('usuarios/<int:perfil_id>/excluir/', usuarios.excluir_usuario, name='usuarios_excluir'),

    path('instagram/conectar/', views.instagram_conectar, name='instagram_conectar'),
    path('instagram/callback/', views.instagram_callback, name='instagram_callback'),
    path('instagram/desconectar/', views.instagram_desconectar, name='instagram_desconectar'),

    # Várias contas por pessoa: trocar a conta aberta e desconectar o Instagram de uma delas.
    path('contas/<int:conta_id>/usar/', contas.usar_conta, name='usar_conta'),
    path('contas/<int:conta_id>/desconectar/', contas.desconectar_conta, name='desconectar_conta'),

    # Landing page da empresa.
    path('plataforma/', meta.apresentacao, name='apresentacao'),

    # Públicas, exigidas pela Meta para a análise do app.
    path('privacidade/', meta.privacidade, name='privacidade'),
    path('termos/', meta.termos, name='termos'),
    path('exclusao-de-dados/', meta.exclusao_de_dados, name='exclusao_de_dados'),
    path('instagram/desautorizar/', meta.instagram_desautorizar, name='instagram_desautorizar'),
    path('instagram/exclusao/', meta.instagram_exclusao, name='instagram_exclusao'),
]
