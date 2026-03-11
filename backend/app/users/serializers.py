from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.core.validators import RegexValidator
from .models import User, Post, Document, Category, Subhead, AuditLog

_phone_regex = RegexValidator(r'^\d{10}$', 'Phone number must be exactly 10 digits.')

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(
        required=False, allow_null=True, allow_blank=True,
        validators=[
            UniqueValidator(queryset=User.objects.all(), message='A user with this email already exists.'),
        ],
    )
    phone_number = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        validators=[
            _phone_regex,
            UniqueValidator(queryset=User.objects.all(), message='A user with this phone number already exists.'),
        ],
    )

    class Meta:
        model = User
        fields = ['HRMS_ID', 'email', 'password', 'phone_number', 'user_status', 'is_staff']
        read_only_fields = ['user_status', 'is_staff']

    def validate_email(self, value):
        """Treat blank/empty string as None (no email)."""
        if value in (None, ''):
            return None
        return value

    def validate_phone_number(self, value):
        """Treat blank/empty string as None (no phone)."""
        if value in (None, ''):
            return None
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            HRMS_ID=validated_data['HRMS_ID'],
            email=validated_data.get('email', None),
            password=validated_data['password'],
            phone_number=validated_data.get('phone_number', None),
        )
        return user

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class CategoryDetailSerializer(serializers.ModelSerializer):
    subhead_count = serializers.IntegerField(read_only=True)
    drawing_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'subhead_count', 'drawing_count']


class SubheadSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')

    class Meta:
        model = Subhead
        fields = ['id', 'name', 'category', 'category_name', 'crawler_id', 'drawing_count']


class DocumentSerializer(serializers.ModelSerializer):
    
    # Get the names from the request, which might contain new categories that need to be created, or existing categories that need to be linked
    category_names = serializers.ListField(
        child = serializers.CharField(), write_only=True, required=False
    )

    category = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            'document_id',
            'name',
            'version',
            'link',
            'internal_link',
            'category',
            'category_names',
            'last_updated',
            'drawing_id',
            'description',
            'content_type',
            'file_size',
            'is_archived',
            'subhead',
        ]
    
    def create(self, validated_data):
        category_names = validated_data.pop('category_names', [])
        document = Document.objects.create(**validated_data)

        for name in category_names:
            cat, created = Category.objects.get_or_create(name=name)
            document.category.add(cat)
        
        return document
    
class PostSerializer(serializers.ModelSerializer):
    user_hrms_id = serializers.ReadOnlyField(source='user.HRMS_ID')
    document_id = serializers.SlugRelatedField(
        slug_field='document_id',
        queryset=Document.objects.all(),
        source='document',
    )

    class Meta:
        model = Post
        fields = ['id', 'user_hrms_id', 'post_type', 'content', 'created_at', 'document_id', 'parent']
        read_only_fields = ['user_hrms_id', 'created_at']

    def validate(self, attrs):
        parent = attrs.get('parent')
        document = attrs.get('document')
        if parent and document and parent.document != document:
            raise serializers.ValidationError(
                {"parent": "Reply must belong to the same document as the parent post."}
            )
        return attrs

class AuditLogSerializer(serializers.ModelSerializer):
    user_hrms_id = serializers.ReadOnlyField(source='user.HRMS_ID')

    class Meta:
        model = AuditLog
        fields = ['id', 'user_hrms_id', 'action', 'target_type', 'target_id', 'metadata', 'created_at']