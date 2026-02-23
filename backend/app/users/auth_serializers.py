from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class HRMSTokenSerializer(TokenObtainPairSerializer):
    username_field = 'HRMS_ID'

    @classmethod

    def get_token(cls, user):
        token = super().get_token(user)

        token["HRMS_ID"] = user.HRMS_ID
        token["email"] = user.email

        return token
    