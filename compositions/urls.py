from django.urls import path

from . import views

app_name = 'compositions'
urlpatterns = [
    path('', views.catalogue, name='list'),
    path('<slug:slug>/', views.detail, name='detail'),
]
