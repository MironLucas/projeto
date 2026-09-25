from django.contrib.auth import views as auth_views
from django.urls import path

from . import agenda, publico, quadro, views

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('publico/', publico.publico, name='publico'),

    path('programacao/', agenda.programacao, name='programacao'),
    path('programacao/itens/', agenda.adicionar_item, name='agenda_adicionar'),
    path('programacao/itens/<int:item_id>/concluir/', agenda.alternar_item, name='agenda_alternar'),
    path('programacao/itens/<int:item_id>/excluir/', agenda.excluir_item, name='agenda_excluir'),

    path('tarefas/', quadro.tarefas, name='tarefas'),
    path('tarefas/listas/', quadro.criar_lista, name='quadro_criar_lista'),
    path('tarefas/listas/<int:lista_id>/renomear/', quadro.renomear_lista, name='quadro_renomear_lista'),
    path('tarefas/listas/<int:lista_id>/excluir/', quadro.excluir_lista, name='quadro_excluir_lista'),
    path('tarefas/listas/<int:lista_id>/cartoes/', quadro.criar_cartao, name='quadro_criar_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/mover/', quadro.mover_cartao, name='quadro_mover_cartao'),
    path('tarefas/cartoes/<int:cartao_id>/excluir/', quadro.excluir_cartao, name='quadro_excluir_cartao'),

    path('instagram/conectar/', views.instagram_conectar, name='instagram_conectar'),
    path('instagram/callback/', views.instagram_callback, name='instagram_callback'),
    path('instagram/desconectar/', views.instagram_desconectar, name='instagram_desconectar'),
]
