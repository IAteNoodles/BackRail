import logging
import subprocess
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .metrics import (
    record_crawler_completion,
    record_crawler_log_line,
    record_crawler_queue_depth,
    set_crawler_active,
)
from .models import CrawlerRun

logger = logging.getLogger('users.crawler')

RUNNING_STATUSES = (CrawlerRun.STATUS_QUEUED, CrawlerRun.STATUS_RUNNING)


def _cache_key(run_id):
    return f'crawler-run:{run_id}:logs'


def _get_logs(run):
    try:
        cached_logs = cache.get(_cache_key(run.id))
    except Exception:
        cached_logs = None
    if isinstance(cached_logs, list):
        return cached_logs
    return list(run.log_tail or [])


def _set_logs(run_id, logs):
    try:
        cache.set(_cache_key(run_id), logs, timeout=settings.CRAWLER_LOG_CACHE_TTL)
    except Exception:
        logger.debug('Could not cache crawler logs for run %s', run_id, exc_info=True)


def _update_queue_depth():
    if not settings.CRAWLER_USE_QUEUE:
        record_crawler_queue_depth('crawler', 0)
        return

    try:
        import django_rq

        queue = django_rq.get_queue('crawler')
        record_crawler_queue_depth('crawler', queue.count)
    except Exception:
        logger.debug('Could not inspect crawler queue depth', exc_info=True)


def get_current_crawler_run(run_id=None):
    queryset = CrawlerRun.objects.all()
    if run_id:
        return queryset.filter(pk=run_id).first()

    active = queryset.filter(status__in=RUNNING_STATUSES).order_by('-created_at').first()
    if active:
        return active
    return queryset.order_by('-created_at').first()


def get_crawler_logs(run, since=0):
    logs = _get_logs(run)
    total_lines = run.total_log_lines or len(logs)
    first_available_index = max(total_lines - len(logs), 0)
    effective_since = max(since, first_available_index)
    start = max(effective_since - first_available_index, 0)
    return logs[start:], total_lines, since < first_available_index


def start_crawler_run(user):
    active_run = CrawlerRun.objects.filter(status__in=RUNNING_STATUSES).order_by('-created_at').first()
    if active_run:
        set_crawler_active(True)
        _update_queue_depth()
        return active_run, 'already_running'

    execution_mode = CrawlerRun.EXECUTION_QUEUE if settings.CRAWLER_USE_QUEUE else CrawlerRun.EXECUTION_THREAD
    run = CrawlerRun.objects.create(
        initiated_by=user,
        status=CrawlerRun.STATUS_QUEUED,
        execution_mode=execution_mode,
        storage_root=str(settings.RDSO_STORAGE_ROOT),
    )
    _set_logs(run.id, [])

    if settings.CRAWLER_USE_QUEUE:
        try:
            import django_rq

            queue = django_rq.get_queue('crawler')
            job = queue.enqueue(execute_crawler_run, run.id, job_timeout=settings.CRAWLER_JOB_TIMEOUT)
            run.job_id = job.id
            run.save(update_fields=['job_id', 'updated_at'])
            set_crawler_active(True)
            _update_queue_depth()
            return run, 'started'
        except Exception as exc:
            logger.exception('Failed to enqueue crawler run %s', run.id)
            run.metadata = {**run.metadata, 'enqueue_error': str(exc)}
            if not settings.CRAWLER_FALLBACK_TO_THREAD:
                run.status = CrawlerRun.STATUS_FAILED
                run.error_message = str(exc)
                run.finished_at = timezone.now()
                run.last_heartbeat = run.finished_at
                run.save(update_fields=['metadata', 'status', 'error_message', 'finished_at', 'last_heartbeat', 'updated_at'])
                _update_queue_depth()
                set_crawler_active(False)
                raise

            run.execution_mode = CrawlerRun.EXECUTION_THREAD
            run.save(update_fields=['metadata', 'execution_mode', 'updated_at'])

    threading.Thread(target=execute_crawler_run, args=(run.id,), daemon=True).start()
    set_crawler_active(True)
    _update_queue_depth()
    return run, 'started'


def execute_crawler_run(run_id):
    run = CrawlerRun.objects.get(pk=run_id)
    started_perf = time.perf_counter()
    logs = _get_logs(run)
    total_lines = run.total_log_lines or len(logs)
    exit_code = None
    error_message = ''

    run.status = CrawlerRun.STATUS_RUNNING
    run.started_at = timezone.now()
    run.last_heartbeat = run.started_at
    run.error_message = ''
    run.save(update_fields=['status', 'started_at', 'last_heartbeat', 'error_message', 'updated_at'])
    set_crawler_active(True)
    _update_queue_depth()

    try:
        crawler_script = Path(settings.RDSO_STORAGE_ROOT) / 'rdso_site_crawler.py'
        proc = subprocess.Popen(
            [
                settings.PYTHON_EXECUTABLE if hasattr(settings, 'PYTHON_EXECUTABLE') else 'python',
                str(crawler_script),
                '--storage-root',
                str(settings.RDSO_STORAGE_ROOT),
            ],
            cwd=str(settings.RDSO_STORAGE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        run.pid = proc.pid
        run.save(update_fields=['pid', 'updated_at'])

        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                total_lines += 1
                logs.append(line)
                logs = logs[-settings.CRAWLER_LOG_TAIL_LIMIT:]
                _set_logs(run.id, logs)
                record_crawler_log_line()

                if total_lines % 25 == 0:
                    run.log_tail = logs
                    run.total_log_lines = total_lines
                    run.last_heartbeat = timezone.now()
                    run.save(update_fields=['log_tail', 'total_log_lines', 'last_heartbeat', 'updated_at'])

        exit_code = proc.wait()
        if exit_code == 0:
            run.status = CrawlerRun.STATUS_SUCCEEDED
        else:
            run.status = CrawlerRun.STATUS_FAILED
            error_message = f'Crawler exited with code {exit_code}'
    except Exception as exc:
        logger.exception('Crawler run %s failed', run.id)
        run.status = CrawlerRun.STATUS_FAILED
        error_message = str(exc)
    finally:
        finished_at = timezone.now()
        run.finished_at = finished_at
        run.last_heartbeat = finished_at
        run.total_log_lines = total_lines
        run.log_tail = logs[-settings.CRAWLER_LOG_TAIL_LIMIT:]
        run.exit_code = exit_code
        run.error_message = error_message
        run.metadata = {
            **run.metadata,
            'duration_seconds': round(time.perf_counter() - started_perf, 3),
        }
        run.save(update_fields=[
            'status',
            'finished_at',
            'last_heartbeat',
            'total_log_lines',
            'log_tail',
            'exit_code',
            'error_message',
            'metadata',
            'updated_at',
        ])
        _set_logs(run.id, run.log_tail)
        set_crawler_active(CrawlerRun.objects.filter(status__in=RUNNING_STATUSES).exclude(pk=run.id).exists())
        record_crawler_completion(
            run.status,
            run.execution_mode,
            time.perf_counter() - started_perf,
        )
        _update_queue_depth()