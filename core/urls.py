from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('programacao/', views.programacao, name='programacao'),
    path('tarefas/', views.tarefas, name='tarefas'),
    path('instagram/conectar/', views.instagram_conectar, name='instagram_conectar'),
    path('instagram/callback/', views.instagram_callback, name='instagram_callback'),
    path('instagram/desconectar/', views.instagram_desconectar, name='instagram_desconectar'),
]
