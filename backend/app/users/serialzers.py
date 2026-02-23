from rest_framework import serializers
from .models import User

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    phone_no = serializers.CharField(source='phone_number', required=False)
    email = serializers.EmailField(required=False)

    class Meta:
        model = User
        fields = ['HRMS_ID', 'email', 'password', 'phone_no']

    def create(self, validated_data):
        user = User.objects.create_user(
            HRMS_ID = validated_data['HRMS_ID'],
            email = validated_data.get('email', None),
            password = validated_data['password'],
            phone_no = validated_data.get('phone_number', None)
        )
        return user
