from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import InvalidToken

from .serializers import PostSerializer, UserSerializer, DocumentSerializer, CategorySerializer, CategoryDetailSerializer, SubheadSerializer, AuditLogSerializer
from .auth_serializers import HRMSTokenSerializer
from .permissions import IsAcceptedUser

import io
import json
import os
import sys
import logging
import subprocess
import threading
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from django.db.models import Count
from .models import Document, User, Post, Category, Subhead, AuditLog
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas
from pypdf import PdfReader, PdfWriter

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
        download_param = request.query_params.get("download")  # None, "true", or "false"

        if document_ids:
            ids_list = [i.strip() for i in document_ids.split(',') if i.strip()]
            documents = Document.objects.filter(document_id__in=ids_list).prefetch_related('category')
        else:
            documents = Document.objects.prefetch_related('category').all()

        # PDF mode: download param is present (either "true" or "false")
        if download_param is not None:
            as_download = download_param.lower() == "true"

            if not document_ids or documents.count() != 1:
                return Response(
                    {"detail": "Specify exactly one document_ids value for PDF view/download."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            document = documents.first()
            log_audit(request.user, 'document_view', 'document', document.document_id,
                      {"download": as_download})
            return _serve_file(document, request.user.HRMS_ID, as_download=as_download)

        # JSON listing mode (no download param)
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

# ---------------- DUMP ----------------

class DumpView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        last_synced = request.query_params.get("last_synced")

        documents = Document.objects.all()
        if last_synced:
            documents = documents.filter(last_updated__gt=last_synced)

        categories = Category.objects.all()
        subheads = Subhead.objects.all()

        return Response({
            "documents": DocumentSerializer(documents, many=True).data,
            "categories": CategorySerializer(categories, many=True).data,
            "subheads": SubheadSerializer(subheads, many=True).data,
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


# ---------------- FILE SERVING ----------------

def _watermark_pdf(pdf_path, watermark_text):
    """Return BytesIO of the PDF at pdf_path with a diagonal watermark on every page."""
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


def _serve_file(document, hrms_id, as_download=False):
    """Stream the file for a Document. Supports RDSO storage or legacy media path."""
    # Determine file path
    if document.storage_path and document.file_name_on_disk:
        file_path = os.path.join(
            str(settings.RDSO_STORAGE_ROOT),
            document.storage_path,
            document.file_name_on_disk,
        )
        allowed_root = os.path.realpath(str(settings.RDSO_STORAGE_ROOT))
    else:
        file_path = os.path.join(settings.MEDIA_ROOT, 'documents', f'{document.document_id}.pdf')
        allowed_root = os.path.realpath(str(settings.MEDIA_ROOT))

    logger.info("_serve_file: doc=%s, download=%s, path=%s", document.document_id, as_download, file_path)

    # Path traversal protection
    resolved = os.path.realpath(file_path)
    if not resolved.startswith(allowed_root):
        logger.warning("_serve_file: path traversal blocked for %s", document.document_id)
        return Response({"detail": "Invalid document path"}, status=status.HTTP_403_FORBIDDEN)

    if not os.path.isfile(file_path):
        logger.warning("_serve_file: file not found at %s", file_path)
        return Response({"detail": "File not found"}, status=status.HTTP_404_NOT_FOUND)

    file_size = os.path.getsize(file_path)
    ct = document.content_type or 'application/pdf'
    is_pdf = ct == 'application/pdf'
    safe_name = document.file_name_on_disk or f'{document.document_id}.pdf'
    logger.info("_serve_file: file exists, size=%d, content_type=%s", file_size, ct)

    try:
        if as_download and is_pdf:
            now_str = timezone.now().strftime('%d-%m-%Y %H:%M:%S')
            watermark_text = f"Downloaded by {hrms_id} at {now_str}"
            file_to_serve = _watermark_pdf(file_path, watermark_text)
            disposition = 'attachment'
        elif as_download:
            file_to_serve = open(file_path, 'rb')
            disposition = 'attachment'
        else:
            file_to_serve = open(file_path, 'rb')
            disposition = 'inline'
    except Exception as e:
        logger.error("_serve_file: processing error for %s: %s", document.document_id, e)
        return Response({"detail": f"File processing error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    response = FileResponse(file_to_serve, content_type=ct)
    response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
    return response


class HealthCheckView(APIView):
    """Simple health check for deployment monitoring."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "timestamp": timezone.now().isoformat()}, status=status.HTTP_200_OK)


# ---------------- CATALOG HIERARCHY ----------------

class CategoryListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request):
        logger.info("CategoryListView: listing categories")
        categories = Category.objects.annotate(
            subhead_count=Count('subheads', distinct=True),
            drawing_count=Count('documents', distinct=True),
        ).order_by('name')
        serializer = CategoryDetailSerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SubheadListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, pk):
        logger.info("SubheadListView: listing subheads for category %s", pk)
        category = get_object_or_404(Category, pk=pk)
        subheads = Subhead.objects.filter(category=category).order_by('name')
        serializer = SubheadSerializer(subheads, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SubheadDocumentListView(APIView):
    permission_classes = [IsAcceptedUser]

    def get(self, request, pk):
        logger.info("SubheadDocumentListView: listing documents for subhead %s", pk)
        subhead = get_object_or_404(Subhead, pk=pk)
        documents = Document.objects.filter(subhead=subhead).prefetch_related('category').order_by('name')
        serializer = DocumentSerializer(documents, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------- ADMIN CRAWLER ----------------

_crawler_lock = threading.Lock()
_crawler_process = None
_crawler_log_lines = []


def _read_stream(stream):
    """Read lines from a single stream and buffer them."""
    global _crawler_log_lines
    if stream is None:
        return
    for raw_line in stream:
        line = raw_line.decode('utf-8', errors='replace').rstrip()
        if line:
            _crawler_log_lines.append(line)
            logger.info("crawler: %s", line)


def _stream_crawler_output(proc):
    """Background thread: read crawler stdout/stderr in parallel."""
    threads = []
    for stream in (proc.stdout, proc.stderr):
        t = threading.Thread(target=_read_stream, args=(stream,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


class RunCrawlerView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        global _crawler_process, _crawler_log_lines
        with _crawler_lock:
            if _crawler_process and _crawler_process.poll() is None:
                logger.info("RunCrawlerView: crawler already running (pid=%d)", _crawler_process.pid)
                return Response({"status": "already_running", "pid": _crawler_process.pid}, status=status.HTTP_409_CONFLICT)

            logger.info("RunCrawlerView: starting crawler")
            _crawler_log_lines = []
            crawler_script = str(Path(settings.RDSO_STORAGE_ROOT) / 'rdso_site_crawler.py')
            _crawler_process = subprocess.Popen(
                [sys.executable, crawler_script, '--storage-root', str(settings.RDSO_STORAGE_ROOT)],
                cwd=str(settings.RDSO_STORAGE_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            threading.Thread(target=_stream_crawler_output, args=(_crawler_process,), daemon=True).start()
            return Response({"status": "started", "pid": _crawler_process.pid}, status=status.HTTP_202_ACCEPTED)


class CrawlerStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        global _crawler_process
        running = _crawler_process is not None and _crawler_process.poll() is None

        meta_path = Path(settings.RDSO_STORAGE_ROOT) / '__meta__.json'
        meta_info = {}
        if meta_path.exists():
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_info = json.load(f)

        totals = meta_info.get('totals', {})
        logger.info("CrawlerStatusView: running=%s", running)
        return Response({
            "running": running,
            "pid": _crawler_process.pid if _crawler_process else None,
            "last_run": meta_info.get('generated_at_utc'),
            "total_files": totals.get('file_count') or totals.get('files'),
            "total_categories": totals.get('category_count') or totals.get('categories'),
            "total_subheads": totals.get('subhead_count') or totals.get('subheads'),
            "total_drawings": totals.get('drawing_count') or totals.get('drawings'),
        }, status=status.HTTP_200_OK)


class CrawlerLogsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        """Return crawler log lines. ?since=N returns lines after index N."""
        since = int(request.query_params.get('since', 0))
        lines = _crawler_log_lines[since:]
        running = _crawler_process is not None and _crawler_process.poll() is None
        return Response({
            "running": running,
            "offset": since + len(lines),
            "lines": lines,
        }, status=status.HTTP_200_OK)


class ImportCatalogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        from django.core.management import call_command
        from io import StringIO

        logger.info("ImportCatalogView: triggered by %s", request.user.HRMS_ID)
        out = StringIO()
        call_command('import_rdso_catalog', stdout=out)
        result = out.getvalue()
        logger.info("ImportCatalogView: %s", result.strip())
        return Response({"status": "ok", "output": result.strip()}, status=status.HTTP_200_OK)