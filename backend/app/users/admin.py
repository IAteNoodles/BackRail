from django.contrib import admin
from .models import User, Post, Document, Category, Subhead, AuditLog

admin.site.register(User)
admin.site.register(Post)
admin.site.register(Document)
admin.site.register(Category)
admin.site.register(Subhead)
admin.site.register(AuditLog)