from django.urls import path
from . import views
from .views import LoginView, RegisterView, HelloView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('hello/', HelloView.as_view(), name="hello"),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('registrations/', views.RegistrationListView.as_view(), name='registration-list'),
    path('update_status/', views.UpdateUserStatusView.as_view(), name='update-user-status'),
    ]