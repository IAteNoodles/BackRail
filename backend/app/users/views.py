from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import UntypedToken

from .serialzers import RegisterSerializer
from .auth_serializers import HRMSTokenSerializer


# ---------------- REGISTER ----------------
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "User registered successfully"},
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------- LOGIN ----------------
class LoginView(TokenObtainPairView):
    serializer_class = HRMSTokenSerializer
    permission_classes = [AllowAny]


# ---------------- HELLO (PROTECTED) ----------------
class HelloView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        user = request.user

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