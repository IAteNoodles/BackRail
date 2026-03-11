import io
import os
import logging

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas
from pypdf import PdfReader, PdfWriter

from .models import AuditLog

logger = logging.getLogger("users")


def log_audit(user, action, target_type, target_id='', metadata=None):
    AuditLog.objects.create(
        user=user, action=action,
        target_type=target_type, target_id=str(target_id),
        metadata=metadata or {},
    )


def watermark_pdf(pdf_path, watermark_text):
    """Return BytesIO of the PDF at pdf_path with a diagonal watermark on every page."""
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


def serve_file(document, hrms_id, as_download=False):
    """Stream the file for a Document. Supports RDSO storage or legacy media path."""
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

    logger.info("serve_file: doc=%s, download=%s, path=%s", document.document_id, as_download, file_path)

    # Path traversal protection
    resolved = os.path.realpath(file_path)
    if not resolved.startswith(allowed_root):
        logger.warning("serve_file: path traversal blocked for %s", document.document_id)
        return Response({"detail": "Invalid document path"}, status=status.HTTP_403_FORBIDDEN)

    if not os.path.isfile(file_path):
        logger.warning("serve_file: file not found at %s", file_path)
        return Response({"detail": "File not found"}, status=status.HTTP_404_NOT_FOUND)

    file_size = os.path.getsize(file_path)
    ct = document.content_type or 'application/pdf'
    is_pdf = ct == 'application/pdf'
    safe_name = document.file_name_on_disk or f'{document.document_id}.pdf'
    logger.info("serve_file: file exists, size=%d, content_type=%s", file_size, ct)

    try:
        if as_download and is_pdf:
            now_str = timezone.now().strftime('%d-%m-%Y %H:%M:%S')
            watermark_text = f"Downloaded by {hrms_id} at {now_str}"
            file_to_serve = watermark_pdf(file_path, watermark_text)
            disposition = 'attachment'
        elif as_download:
            file_to_serve = open(file_path, 'rb')
            disposition = 'attachment'
        else:
            file_to_serve = open(file_path, 'rb')
            disposition = 'inline'
    except Exception as e:
        logger.error("serve_file: processing error for %s: %s", document.document_id, e)
        return Response({"detail": f"File processing error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    response = FileResponse(file_to_serve, content_type=ct)
    response['Content-Disposition'] = f'{disposition}; filename="{safe_name}"'
    return response
