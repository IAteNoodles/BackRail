from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractUser

# Create your models here.

class UserManager(BaseUserManager):
    def create_user(self, HRMS_ID, email=None, phone_no=None, password = None, **extra_fields):
        if not HRMS_ID:
            raise ValueError("Users must have an HRMS ID")
        if email:
            email = self.normalize_email(email)
        
        user = self.model(HRMS_ID=HRMS_ID, email=email, phone_number=phone_no, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, HRMS_ID, email=None, password=None, phone_no=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(HRMS_ID, email, phone_no, password, **extra_fields)

class User(AbstractUser):
    username = None
    HRMS_ID = models.CharField(max_length=255, unique=True)
    email = models.EmailField(unique=True, blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=10, blank=True, null=True, unique=True, default=None)
    USERNAME_FIELD = 'HRMS_ID'
    REQUIRED_FIELDS = ['email']
    objects = UserManager()

