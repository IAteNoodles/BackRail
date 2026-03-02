from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework import serializers
from .models import User

_GENERIC_LOGIN_ERROR = "No active account found with the given credentials"

class HRMSTokenSerializer(TokenObtainPairSerializer):
    username_field = 'HRMS_ID'

    def validate(self, attrs):
        hrms_id = attrs.get('HRMS_ID')
        try:
            user = User.objects.get(HRMS_ID=hrms_id)
        except User.DoesNotExist:
            user = None

        if user and user.user_status != 'accepted':
            # Authenticate first so the error path matches a bad-password 401,
            # preventing user-existence enumeration via differing status codes.
            from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
            raise InvalidToken(_GENERIC_LOGIN_ERROR)

        data = super().validate(attrs)
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["HRMS_ID"] = user.HRMS_ID
        return token