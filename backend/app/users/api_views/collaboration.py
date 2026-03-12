from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Document, Post
from ..permissions import IsAcceptedUser
from ..serializers import PostSerializer
from ..utils import log_audit
from .base import logger


class CreatePost(APIView):
    permission_classes = [IsAcceptedUser]

    def post(self, request):
        serializer = PostSerializer(data=request.data)

        if serializer.is_valid():
            post = serializer.save(user=request.user)
            log_audit(request.user, 'post_create', 'document', post.document.document_id)
            logger.info(f"User {request.user.HRMS_ID} created post {post.id}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        logger.warning(f"Failed to create post for user {request.user.HRMS_ID} - Errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PostListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        document_id = request.query_params.get('document_id')
        if not document_id:
            return Response({'error': 'document_id query parameter is required'}, status=status.HTTP_400_BAD_REQUEST)

        posts = Post.objects.filter(document__document_id=document_id)
        serializer = PostSerializer(posts, many=True)
        return Response(serializer.data)


class FeedbackListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, document_id):
        get_object_or_404(Document, document_id=document_id)
        posts = Post.objects.filter(document__document_id=document_id, post_type='feedback')
        serializer = PostSerializer(posts, many=True)
        return Response(serializer.data)


class BatchActionView(APIView):
    permission_classes = [IsAcceptedUser]

    def post(self, request):
        actions = request.data.get('actions', [])
        if not isinstance(actions, list) or not actions:
            return Response({'error': "Provide a non-empty 'actions' array"}, status=status.HTTP_400_BAD_REQUEST)

        results = []
        for idx, action in enumerate(actions):
            serializer = PostSerializer(data={
                'post_type': action.get('type', 'comment'),
                'content': action.get('content', ''),
                'document_id': action.get('document_id'),
                'parent': action.get('parent'),
            })
            if serializer.is_valid():
                post = serializer.save(user=request.user)
                log_audit(request.user, 'batch_action', 'document', post.document.document_id)
                results.append({'index': idx, 'status': 'ok', 'id': post.id})
            else:
                results.append({'index': idx, 'status': 'error', 'errors': serializer.errors})

        logger.info(f"Batch action by {request.user.HRMS_ID}: {len(actions)} items")
        return Response({'results': results}, status=status.HTTP_200_OK)