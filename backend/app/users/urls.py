from django.urls import path
from . import views
from .views import (
    LoginView, RegisterView, HelloView, RegistrationListView,
    UpdateUserStatusView, CreateDocument, CreatePost,
    FeedbackListView, BatchActionView, DumpView,
    DocumentLogView, UserLogView, HealthCheckView,
)
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('hello/', HelloView.as_view(), name="hello"),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('registrations/', RegistrationListView.as_view(), name='registration-list'),
    path('update_status/', UpdateUserStatusView.as_view(), name='update-user-status'),
    path('create_document/', CreateDocument.as_view(), name='create-document'),
    path('create_post/', CreatePost.as_view(), name='create-post'),
    path('documents/', views.DocumentListView.as_view(), name='document-list'),
    path('posts/', views.PostListView.as_view(), name='post-list'),
    path('dump/', DumpView.as_view(), name='dump'),
    path('actions/batch/', BatchActionView.as_view(), name='actions-batch'),
    path('feedback/<str:document_id>/', FeedbackListView.as_view(), name='feedback-list'),
    path('logs/documents/', DocumentLogView.as_view(), name='document-logs'),
    path('logs/users/', UserLogView.as_view(), name='user-logs'),
    path('health/', HealthCheckView.as_view(), name='health-check'),
]