from django.shortcuts import render
# Create your views here.

from django.http import JsonResponse

def hello(request, name):
    return JsonResponse({"message": f"Hello, {name}!"})