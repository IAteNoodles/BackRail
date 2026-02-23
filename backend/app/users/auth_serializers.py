from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class HRMSTokenSerializer(TokenObtainPairSerializer):
    username_field = 'HRMS_ID'