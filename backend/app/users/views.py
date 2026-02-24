from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import UntypedToken

from .serialzers import RegisterSerializer
from .auth_serializers import HRMSTokenSerializer

import logging
from .models import User
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter

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
    
# ---------------- ADMIN ENDPOINTS ----------------

class RegistrationListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='filter',
                description='Filter users by status',
                required=False,
                enum=['pending', 'accepted', 'rejected']
            ),
        ],
        responses={200: "List of users"}
    )
    def get(self, request):
        users = User.objects.all()
        filter = request.query_params.get("filter")
        if filter in ['pending', 'accepted', 'rejected']:
            users = users.filter(user_status=filter)
        user_data = [
            {
                "HRMS_ID": user.HRMS_ID,
                "email": user.email,
                "phone_number": user.phone_number,
                "user_status": user.user_status
            }
            for user in users
        ]
        return Response(user_data, status=status.HTTP_200_OK)

class UpdateUserStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='HRMS_ID',
                description='HRMS ID of the user to update',
                required=True,
            ),
            OpenApiParameter(
                name='status',
                description='New status for the user',
                required=True,
                enum=['accepted', 'rejected']
            ),
        ],
        responses={200: "User status updated"}
    )
    def post(self, request):
        HRMS_ID = request.data.get("HRMS_ID")
        status_value = request.data.get("status")
        if status_value not in ['accepted', 'rejected']:
            return Response({"error": "Invalid status value"}, status=status.HTTP_400_BAD_REQUEST)
        user = get_object_or_404(User, HRMS_ID=HRMS_ID)
        user.user_status = status_value
        user.save()
        logger.info(f"Updated user {HRMS_ID} status to {status_value}")
        return Response({"message": f"User {HRMS_ID} status updated to {status_value}"}, status=status.HTTP_200_OK)
        