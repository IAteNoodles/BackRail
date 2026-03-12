from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.views import TokenObtainPairView

from ..auth_serializers import HRMSTokenSerializer
from ..models import User
from ..permissions import IsAcceptedUser
from ..serializers import UserSerializer
from ..utils import log_audit
from .base import logger


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logger.info(f"Incoming registration for HRMS_ID: {request.data.get('HRMS_ID')}")
        serializer = UserSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            logger.info(f"Successfully registered user with HRMS_ID: {user.HRMS_ID}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        logger.warning(f"Registration failed for HRMS_ID: {request.data.get('HRMS_ID')} - Errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(TokenObtainPairView):
    serializer_class = HRMSTokenSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        hrms_id = request.data.get('HRMS_ID')
        logger.info(f"Login attempt for HRMS_ID: {hrms_id}")
        try:
            response = super().post(request, *args, **kwargs)
        except (InvalidToken, AuthenticationFailed, serializers.ValidationError):
            user = User.objects.filter(HRMS_ID=hrms_id).first()
            if user and user.user_status != 'accepted':
                log_audit(user, 'user_login', 'user', hrms_id, {'blocked': True, 'reason': user.user_status})
                logger.warning(f"Login blocked for HRMS_ID: {hrms_id} (status: {user.user_status})")
            raise
        user = User.objects.filter(HRMS_ID=hrms_id).first()
        if user:
            log_audit(user, 'user_login', 'user', user.HRMS_ID)
        logger.info(f"Login successful for HRMS_ID: {hrms_id}")
        return response


class HelloView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)