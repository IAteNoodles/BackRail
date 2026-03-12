from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Category, Document, Subhead
from ..permissions import IsAcceptedUser
from ..serializers import CategoryDetailSerializer, DocumentSerializer, SubheadSerializer
from ..utils import log_audit, serve_file
from .base import logger


class CreateDocument(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        serializer = DocumentSerializer(data=request.data)
        if serializer.is_valid():
            document = serializer.save()
            log_audit(request.user, 'document_create', 'document', document.document_id)
            logger.info(f"Document {document.document_id} created by {request.user.HRMS_ID}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DocumentListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        document_ids = request.query_params.get('document_ids')
        category_name = request.query_params.get('category')
        download_param = request.query_params.get('download')

        if document_ids:
            ids_list = [item.strip() for item in document_ids.split(',') if item.strip()]
            documents = Document.objects.filter(document_id__in=ids_list).prefetch_related('category')
        else:
            documents = Document.objects.prefetch_related('category').all()

        if category_name:
            documents = documents.filter(category__name=category_name).distinct()

        documents = documents.order_by('name')

        if download_param is not None:
            as_download = download_param.lower() == 'true'

            if not document_ids or documents.count() != 1:
                return Response(
                    {'detail': 'Specify exactly one document_ids value for PDF view/download.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            document = documents.first()
            log_audit(request.user, 'document_view', 'document', document.document_id, {'download': as_download})
            return serve_file(document, request.user.HRMS_ID, as_download=as_download)

        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data)


class CategoryListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        logger.info('CategoryListView: listing categories')
        categories = Category.objects.annotate(
            subhead_count=Count('subheads', distinct=True),
            drawing_count=Count('documents', distinct=True),
        ).order_by('name')
        serializer = CategoryDetailSerializer(categories, many=True)
        return Response(serializer.data)


class SubheadListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, pk):
        logger.info('SubheadListView: listing subheads for category %s', pk)
        category = get_object_or_404(Category, pk=pk)
        subheads = Subhead.objects.filter(category=category).order_by('name')
        serializer = SubheadSerializer(subheads, many=True)
        return Response(serializer.data)


class SubheadDocumentListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, pk):
        logger.info('SubheadDocumentListView: listing documents for subhead %s', pk)
        subhead = get_object_or_404(Subhead, pk=pk)
        documents = Document.objects.filter(subhead=subhead).prefetch_related('category').order_by('name')
        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data)