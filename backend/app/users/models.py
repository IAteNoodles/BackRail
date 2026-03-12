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

    class Meta(AbstractUser.Meta):
        ordering = ['HRMS_ID']

class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    def __str__(self):
        return self.name


class Subhead(models.Model):
    name = models.CharField(max_length=500)
    category = models.ForeignKey(Category, related_name='subheads', on_delete=models.CASCADE)
    crawler_id = models.CharField(max_length=50, blank=True, default='')
    source_url = models.URLField(blank=True, default='', max_length=1000)
    drawing_count = models.IntegerField(default=0)

    class Meta:
        unique_together = [('name', 'category')]

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class Document(models.Model):
    document_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=50, default='Current')
    link = models.URLField(blank=True, default='', max_length=1000)
    internal_link = models.URLField(blank=True, default='', max_length=1000)
    category = models.ManyToManyField('Category', related_name='documents', blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    # RDSO crawler fields
    drawing_id = models.IntegerField(unique=True, null=True, blank=True)
    subhead = models.ForeignKey(Subhead, null=True, blank=True, related_name='documents', on_delete=models.SET_NULL)
    description = models.TextField(blank=True, default='')
    storage_path = models.CharField(max_length=1000, blank=True, default='')
    file_name_on_disk = models.CharField(max_length=500, blank=True, default='')
    content_type = models.CharField(max_length=100, blank=True, default='application/pdf')
    file_size = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default='')
    source_url = models.URLField(blank=True, default='', max_length=1000)
    source_file_url = models.URLField(blank=True, default='', max_length=1000)
    is_archived = models.BooleanField(default=False)
    crawled_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (v{self.version})"

    class Meta:
        ordering = ['document_id']

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

    class Meta:
        ordering = ['-created_at']


class CrawlerRun(models.Model):
    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'

    EXECUTION_QUEUE = 'queue'
    EXECUTION_THREAD = 'thread'

    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_FAILED, 'Failed'),
    ]

    EXECUTION_MODE_CHOICES = [
        (EXECUTION_QUEUE, 'Queue'),
        (EXECUTION_THREAD, 'Thread'),
    ]

    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='crawler_runs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    execution_mode = models.CharField(max_length=20, choices=EXECUTION_MODE_CHOICES, default=EXECUTION_QUEUE)
    job_id = models.CharField(max_length=255, blank=True, default='')
    storage_root = models.CharField(max_length=1000, blank=True, default='')
    pid = models.IntegerField(null=True, blank=True)
    queued_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    total_log_lines = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    log_tail = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CrawlerRun#{self.pk} {self.status}"

    class Meta:
        ordering = ['-created_at']

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

    class Meta:
        ordering = ['-created_at']
