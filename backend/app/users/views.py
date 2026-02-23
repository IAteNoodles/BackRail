from django.shortcuts import render
# Create your views here.

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .models import User


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serialzers import RegisterSerializer
from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.views import TokenObtainPairView
from .auth_serializers import HRMSTokenSerializer

def hello(request, name):
    return JsonResponse({"message": f"Hello, {name}!"})

class RegisterView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = RegisterSerializer(data = request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(
                {"message": "User registered successfully"},
                status = status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class LoginView(TokenObtainPairView):
    serializer_class = HRMSTokenSerializer
    permission_classes = [AllowAny]