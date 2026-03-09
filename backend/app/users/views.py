from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import InvalidToken

from .serializers import PostSerializer, UserSerializer, DocumentSerializer, CategorySerializer, AuditLogSerializer
from .auth_serializers import HRMSTokenSerializer
from .permissions import IsAcceptedUser

import io
import logging
from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from .models import Document, User, Post, Category, AuditLog
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter

logger = logging.getLogger("users")


def log_audit(user, action, target_type, target_id='', metadata=None):
    AuditLog.objects.create(
        user=user, action=action,
        target_type=target_type, target_id=str(target_id),
        metadata=metadata or {},
    )

# ---------------- REGISTER ----------------
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


# ---------------- LOGIN ----------------
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
                log_audit(user, 'user_login', 'user', hrms_id,
                          {"blocked": True, "reason": user.user_status})
                logger.warning(f"Login blocked for HRMS_ID: {hrms_id} (status: {user.user_status})")
            raise
        user = User.objects.filter(HRMS_ID=hrms_id).first()
        if user:
            log_audit(user, 'user_login', 'user', user.HRMS_ID)
        logger.info(f"Login successful for HRMS_ID: {hrms_id}")
        return response

# ---------------- HELLO (PROTECTED) ----------------
class HelloView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
        responses={200: UserSerializer(many=True)}
    )
    def get(self, request):
        users = User.objects.all()
        status_filter = request.query_params.get("filter")

        if status_filter in ['pending', 'accepted', 'rejected']:
            users = users.filter(user_status=status_filter)

        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class UpdateUserStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "HRMS_ID": {"type": "string"},
                    "status": {"type": "string", "enum": ["accepted", "rejected"]}
                },
                "required": ["HRMS_ID", "status"]
            }
        },
        responses={200: UserSerializer}
    )
    def post(self, request):
        HRMS_ID = request.data.get("HRMS_ID")
        status_value = request.data.get("status")

        if status_value not in ['accepted', 'rejected']:
            return Response({"error": "Invalid status value"}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, HRMS_ID=HRMS_ID)
        old_status = user.user_status
        user.user_status = status_value
        user.save()

        log_audit(request.user, 'user_status_change', 'user', HRMS_ID,
                  {"old_status": old_status, "new_status": status_value})
        logger.info(f"Updated user {HRMS_ID} status to {status_value}")
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ---------------- POSTS ----------------

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
        document_id = request.query_params.get("document_id")
        if not document_id:
            return Response({"error": "document_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        posts = Post.objects.filter(document__document_id=document_id)
        serializer = PostSerializer(posts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ---------------- DOCUMENTS ----------------

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
        document_ids = request.query_params.get("document_ids")
        download = request.query_params.get("download", "false").lower() == "true"

        if document_ids:
            documents = Document.objects.filter(document_id__in=document_ids.split(','))
        else:
            documents = Document.objects.all()

        if download:
            # Audit log only for download operations
            AuditLog.objects.bulk_create([
                AuditLog(
                    user=request.user, action='document_view',
                    target_type='document', target_id=doc.document_id,
                    metadata={"download": True},
                )
                for doc in documents
            ])
            if documents.count() == 1:
                return _serve_pdf(documents.first(), request.user.HRMS_ID, as_download=True)
            return Response({"detail": "Download supports single document only"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ---------------- FEEDBACK ----------------

class FeedbackListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, document_id):
        get_object_or_404(Document, document_id=document_id)
        posts = Post.objects.filter(document__document_id=document_id, post_type='feedback')
        serializer = PostSerializer(posts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ---------------- BATCH ACTIONS ----------------

class BatchActionView(APIView):
    permission_classes = [IsAcceptedUser]

    def post(self, request):
        actions = request.data.get("actions", [])
        if not isinstance(actions, list) or not actions:
            return Response({"error": "Provide a non-empty 'actions' array"}, status=status.HTTP_400_BAD_REQUEST)

        results = []
        for idx, action in enumerate(actions):
            serializer = PostSerializer(data={
                "post_type": action.get("type", "comment"),
                "content": action.get("content", ""),
                "document_id": action.get("document_id"),
                "parent": action.get("parent"),
            })
            if serializer.is_valid():
                post = serializer.save(user=request.user)
                log_audit(request.user, 'batch_action', 'document', post.document.document_id)
                results.append({"index": idx, "status": "ok", "id": post.id})
            else:
                results.append({"index": idx, "status": "error", "errors": serializer.errors})

        logger.info(f"Batch action by {request.user.HRMS_ID}: {len(actions)} items")
        return Response({"results": results}, status=status.HTTP_200_OK)

# ---------------- DUMP (MOCK) ----------------

class DumpView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        last_synced = request.query_params.get("last_synced")

        documents = Document.objects.all()
        if last_synced:
            documents = documents.filter(last_updated__gt=last_synced)

        categories = Category.objects.all()

        return Response({
            "documents": DocumentSerializer(documents, many=True).data,
            "categories": CategorySerializer(categories, many=True).data,
            "timestamp": timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)

# ---------------- ADMIN LOGS ----------------

class DocumentLogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        logs = AuditLog.objects.filter(target_type='document').order_by('-created_at')
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class UserLogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        logs = AuditLog.objects.filter(target_type='user').order_by('-created_at')
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------- PDF HELPERS ----------------

def _watermark_pdf(pdf_path, watermark_text):
    """Return BytesIO of the PDF at pdf_path with a diagonal watermark on every page."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas
    from pypdf import PdfReader, PdfWriter

    # Build a one-page watermark overlay
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 36)
    c.setFillAlpha(0.15)
    c.translate(letter[0] / 2, letter[1] / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, watermark_text)
    c.save()
    buf.seek(0)
    watermark_page = PdfReader(buf).pages[0]

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        page.merge_page(watermark_page)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def _serve_pdf(document, hrms_id, as_download=False):
    """Stream the PDF file for a Document, with watermark."""
    import os
    pdf_path = os.path.join(settings.MEDIA_ROOT, 'documents', f'{document.document_id}.pdf')
    if not os.path.isfile(pdf_path):
        return Response({"detail": "PDF file not found"}, status=status.HTTP_404_NOT_FOUND)

    if as_download:
        now_str = timezone.now().strftime('%d-%m-%Y %H:%M:%S')
        watermark_text = f"Downloaded by {hrms_id} at {now_str}"
    else:
        watermark_text = f"RDSO - {hrms_id}"

    watermarked = _watermark_pdf(pdf_path, watermark_text)
    disposition = 'attachment' if as_download else 'inline'
    response = FileResponse(watermarked, content_type='application/pdf')
    response['Content-Disposition'] = f'{disposition}; filename="{document.document_id}.pdf"'
    return response


class DocumentPdfView(APIView):
    """Serve a single document PDF inline (for viewer) or as download."""
    permission_classes = [IsAcceptedUser]

    def get(self, request, document_id):
        document = get_object_or_404(Document, document_id=document_id)
        as_download = request.query_params.get("download", "false").lower() == "true"
        log_audit(request.user, 'document_view', 'document', document.document_id,
                  {"download": as_download})
        return _serve_pdf(document, request.user.HRMS_ID, as_download=as_download)