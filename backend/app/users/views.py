from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import UntypedToken

from .serialzers import RegisterSerializer
from .auth_serializers import HRMSTokenSerializer

import logging

logger = logging.getLogger("users")

# ---------------- REGISTER ----------------
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logger.info(f"Incoming registration for HRMS_ID: {request.data.get('HRMS_ID')}")
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            logger.info(f"Successfully registered user with HRMS_ID: {user.HRMS_ID}")
            return Response(
                {"message": "User registered successfully"},
                status=status.HTTP_201_CREATED
            )

        logger.warning(f"Registration failed for HRMS_ID: {request.data.get('HRMS_ID')} - Errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------- LOGIN ----------------
class LoginView(TokenObtainPairView):
    serializer_class = HRMSTokenSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        logger.info(f"Login attempt for HRMS_ID: {request.data.get('HRMS_ID')}")
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            logger.info(f"Login successful for HRMS_ID: {request.data.get('HRMS_ID')}")
        else:
            logger.warning(f"Login failed for HRMS_ID: {request.data.get('HRMS_ID')}")
        return response


# ---------------- HELLO (PROTECTED) ----------------
class HelloView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        logger.info(f"Authenticated request to /HELLO from user: {user.HRMS_ID}")

        # extract JWT
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")

        # decode JWT payload
        decoded_token = UntypedToken(token)

        return Response({
            "user": {
                "HRMS_ID": user.HRMS_ID,
                "email": user.email,
                "phone_number": user.phone_number,
            },
            "jwt": {
                "access_token": token
            }
        })