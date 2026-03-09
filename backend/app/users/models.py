from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractUser
from django.core.validators import RegexValidator
from django.utils import timezone

# Create your models here.

class UserManager(BaseUserManager):
    def create_user(self, HRMS_ID, password=None, email=None, phone_number=None, **extra_fields):
        if not HRMS_ID:
            raise ValueError("Users must have an HRMS ID")
        if email:
            email = self.normalize_email(email)
        
        user = self.model(HRMS_ID=HRMS_ID, email=email, phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_staff(self, HRMS_ID, email=None, password=None, phone_number=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        return self.create_user(HRMS_ID, password=password, email=email, phone_number=phone_number, **extra_fields)

    def create_superuser(self, HRMS_ID, email=None, password=None, phone_number=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(HRMS_ID, password=password, email=email, phone_number=phone_number, **extra_fields)

class User(AbstractUser):
    username = None
    HRMS_ID = models.CharField(max_length=255, unique=True)
    email = models.EmailField(unique=True, blank=True, null=True, default=None)
    phone_number = models.CharField(
        max_length=10, blank=True, null=True, unique=True, default=None,
        validators=[RegexValidator(r'^\d{10}$', 'Phone number must be exactly 10 digits.')]
    )
    user_status = models.CharField(max_length=10, choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending')
    USERNAME_FIELD = 'HRMS_ID'
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.HRMS_ID

class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    def __str__(self):
        return self.name

class Document(models.Model):
    document_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    link = models.URLField()
    internal_link = models.URLField()
    category = models.ManyToManyField('Category', related_name='documents')
    last_updated = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"{self.name} (v{self.version})"

class Post(models.Model):
    POST_TYPES = [
        ('comment', 'Comment'),
        ('feedback', 'Feedback')
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    post_type = models.CharField(choices=POST_TYPES, max_length=20, default='comment')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='posts', null=False, blank=False)
    def __str__(self):
        return f"{self.post_type} by {self.user.HRMS_ID} at {self.created_at}"

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('user_login', 'User Login'),
        ('user_status_change', 'User Status Change'),
        ('document_create', 'Document Create'),
        ('document_view', 'Document View'),
        ('post_create', 'Post Create'),
        ('batch_action', 'Batch Action'),
    ]
    TARGET_CHOICES = [
        ('document', 'Document'),
        ('user', 'User'),
    ]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    target_id = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.action} by {self.user} on {self.target_type}:{self.target_id}"
