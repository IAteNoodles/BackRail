import json
import time
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..crawler import get_crawler_logs, get_current_crawler_run, start_crawler_run
from ..metrics import record_catalog_import, record_crawler_request, set_crawler_active
from ..models import AuditLog, CrawlerRun, User
from ..serializers import AuditLogSerializer, UserSerializer
from ..utils import log_audit
from .base import logger


class RegistrationListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='filter',
                description='Filter users by status',
                required=False,
                enum=['pending', 'accepted', 'rejected'],
            ),
        ],
        responses={200: UserSerializer(many=True)},
    )
    def get(self, request):
        users = User.objects.all()
        status_filter = request.query_params.get('filter')

        if status_filter in ['pending', 'accepted', 'rejected']:
            users = users.filter(user_status=status_filter)

        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)


class UpdateUserStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'HRMS_ID': {'type': 'string'},
                    'status': {'type': 'string', 'enum': ['accepted', 'rejected']},
                },
                'required': ['HRMS_ID', 'status'],
            }
        },
        responses={200: UserSerializer},
    )
    def post(self, request):
        hrms_id = request.data.get('HRMS_ID')
        status_value = request.data.get('status')

        if status_value not in ['accepted', 'rejected']:
            return Response({'error': 'Invalid status value'}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, HRMS_ID=hrms_id)
        old_status = user.user_status
        user.user_status = status_value
        user.save()

        log_audit(request.user, 'user_status_change', 'user', hrms_id, {'old_status': old_status, 'new_status': status_value})
        logger.info(f'Updated user {hrms_id} status to {status_value}')
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DocumentLogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        logs = AuditLog.objects.filter(target_type='document').order_by('-created_at')
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)


class UserLogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        logs = AuditLog.objects.filter(target_type='user').order_by('-created_at')
        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok', 'timestamp': timezone.now().isoformat()}, status=status.HTTP_200_OK)


class RunCrawlerView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        try:
            run, outcome = start_crawler_run(request.user)
        except Exception as exc:
            set_crawler_active(False)
            record_crawler_request('launch_error')
            logger.exception('RunCrawlerView failed to start crawler')
            return Response({'status': 'error', 'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if outcome == 'already_running':
            record_crawler_request('already_running')
            return Response({
                'status': 'already_running',
                'pid': run.pid,
                'run_id': run.id,
                'job_id': run.job_id,
            }, status=status.HTTP_409_CONFLICT)

        logger.info('RunCrawlerView: started crawler run %s', run.id)
        record_crawler_request('started')
        return Response({
            'status': 'started',
            'pid': run.pid,
            'run_id': run.id,
            'job_id': run.job_id,
        }, status=status.HTTP_202_ACCEPTED)


class CrawlerStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        run_id = request.query_params.get('run_id')
        run = get_current_crawler_run(run_id=run_id)
        running = bool(run and run.status in (CrawlerRun.STATUS_QUEUED, CrawlerRun.STATUS_RUNNING))
        set_crawler_active(running)

        meta_path = Path(settings.RDSO_STORAGE_ROOT) / '__meta__.json'
        meta_info = {}
        if meta_path.exists():
            with open(meta_path, 'r', encoding='utf-8') as handle:
                meta_info = json.load(handle)

        totals = meta_info.get('totals', {})
        logger.info('CrawlerStatusView: running=%s', running)
        return Response({
            'running': running,
            'pid': run.pid if run else None,
            'run_id': run.id if run else None,
            'job_id': run.job_id if run else None,
            'status': run.status if run else 'idle',
            'execution_mode': run.execution_mode if run else None,
            'error': run.error_message if run else '',
            'last_run': run.finished_at.isoformat() if run and run.finished_at else meta_info.get('generated_at_utc'),
            'queued_at': run.queued_at.isoformat() if run else None,
            'started_at': run.started_at.isoformat() if run and run.started_at else None,
            'finished_at': run.finished_at.isoformat() if run and run.finished_at else None,
            'total_log_lines': run.total_log_lines if run else 0,
            'total_files': totals.get('file_count') or totals.get('files'),
            'total_categories': totals.get('category_count') or totals.get('categories'),
            'total_subheads': totals.get('subhead_count') or totals.get('subheads'),
            'total_drawings': totals.get('drawing_count') or totals.get('drawings'),
        }, status=status.HTTP_200_OK)


class CrawlerLogsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        since = int(request.query_params.get('since', 0))
        run_id = request.query_params.get('run_id')
        run = get_current_crawler_run(run_id=run_id)

        if not run:
            return Response({
                'running': False,
                'offset': 0,
                'lines': [],
                'run_id': None,
                'status': 'idle',
                'truncated': False,
            }, status=status.HTTP_200_OK)

        lines, offset, truncated = get_crawler_logs(run, since)
        running = run.status in (CrawlerRun.STATUS_QUEUED, CrawlerRun.STATUS_RUNNING)
        return Response({
            'running': running,
            'offset': offset,
            'lines': lines,
            'run_id': run.id,
            'status': run.status,
            'truncated': truncated,
        }, status=status.HTTP_200_OK)


class ImportCatalogView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        logger.info('ImportCatalogView: triggered by %s', request.user.HRMS_ID)
        out = StringIO()
        started_at = time.perf_counter()
        outcome = 'success'
        try:
            call_command('import_rdso_catalog', stdout=out)
        except Exception:
            outcome = 'error'
            raise
        finally:
            record_catalog_import(outcome, time.perf_counter() - started_at)
        result = out.getvalue()
        logger.info('ImportCatalogView: %s', result.strip())
        return Response({'status': 'ok', 'output': result.strip()}, status=status.HTTP_200_OK)