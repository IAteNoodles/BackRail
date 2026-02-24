from rest_framework import serializers
from .models import User, Post, Document, Category

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    phone_no = serializers.CharField(source='phone_number', required=False)
    email = serializers.EmailField(required=False)

    class Meta:
        model = User
        fields = ['id', 'HRMS_ID', 'email', 'password', 'phone_no', 'user_status']

    def create(self, validated_data):
        user = User.objects.create_user(
            HRMS_ID = validated_data['HRMS_ID'],
            email = validated_data.get('email', None),
            password = validated_data['password'],
            phone_no = validated_data.get('phone_number', None)
        )
        return user

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'
    
class DocumentSerializer(serializers.ModelSerializer):
    
    # Get the names from the request, which might contain new categories that need to be created, or existing categories that need to be linked
    category_names = serializers.ListField(
        child = serializers.CharField(), write_only=True, required=False
    )

    category = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            'id',
            'document_id',
            'name',
            'version',
            'link',
            'internal_link',
            'category',
            'category_names',
            'last_updated'
        ]
    
    def create(self, validated_data):
        category_names = validated_data.pop('category_names', [])
        document = Document.objects.create(**validated_data)

        for name in category_names:
            cat, created = Category.objects.get_or_create(name=name)
            document.category.add(cat)
        
        return document
    
    def update(self, instance, validated_data):
        category_names = validated_data.pop('category_names', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update categories
        if category_names:
            instance.category.clear()
            for name in category_names:
                cat, created = Category.objects.get_or_create(name=name)
                instance.category.add(cat)
        return instance
    class Meta:
        model = Document
        fields = '__all__'

class PostSerializer(serializers.ModelSerializer):
    user_hrms_id = serializers.ReadOnlyField(source='user.HRMS_ID')

    class Meta:
        model = Post
        fields = ['id', 'user', 'user_hrms_id', 'post_type', 'content', 'created_at', 'document_id', 'parent']

        read_only_fields = ['created_at']
    