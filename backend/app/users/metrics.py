from prometheus_client import Counter, Gauge, Histogram


_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

crawler_run_requests_total = Counter(
    'railway_crawler_run_requests_total',
    'Crawler run requests grouped by outcome.',
    ['outcome'],
)

crawler_active_runs = Gauge(
    'railway_crawler_active_runs',
    'Number of crawler runs currently active in this process.',
)

crawler_log_lines_total = Counter(
    'railway_crawler_log_lines_total',
    'Crawler log lines consumed by the API process.',
)

crawler_queue_depth = Gauge(
    'railway_crawler_queue_depth',
    'Current queue depth for crawler jobs.',
    ['queue_name'],
)

crawler_run_duration_seconds = Histogram(
    'railway_crawler_run_duration_seconds',
    'Crawler run duration in seconds.',
    ['status', 'execution_mode'],
    buckets=_BUCKETS + (60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)

crawler_run_completions_total = Counter(
    'railway_crawler_run_completions_total',
    'Crawler run completions grouped by status and execution mode.',
    ['status', 'execution_mode'],
)

catalog_import_requests_total = Counter(
    'railway_catalog_import_requests_total',
    'Catalog import requests grouped by outcome.',
    ['outcome'],
)

catalog_import_duration_seconds = Histogram(
    'railway_catalog_import_duration_seconds',
    'Catalog import request duration in seconds.',
    buckets=_BUCKETS,
)

document_dump_requests_total = Counter(
    'railway_document_dump_requests_total',
    'Document dump requests grouped by mode.',
    ['mode'],
)

document_dump_document_count = Histogram(
    'railway_document_dump_document_count',
    'Number of documents returned by dump responses.',
    buckets=(1, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
)

file_serve_requests_total = Counter(
    'railway_file_serve_requests_total',
    'File serving outcomes grouped by mode and content type.',
    ['outcome', 'mode', 'content_type'],
)

file_serve_duration_seconds = Histogram(
    'railway_file_serve_duration_seconds',
    'Time spent preparing a file response.',
    ['mode'],
    buckets=_BUCKETS,
)


def record_crawler_request(outcome):
    crawler_run_requests_total.labels(outcome=outcome).inc()


def set_crawler_active(is_active):
    crawler_active_runs.set(1 if is_active else 0)


def record_crawler_log_line():
    crawler_log_lines_total.inc()


def record_crawler_queue_depth(queue_name, depth):
    crawler_queue_depth.labels(queue_name=queue_name).set(depth)


def record_crawler_completion(status, execution_mode, duration_seconds):
    crawler_run_completions_total.labels(status=status, execution_mode=execution_mode).inc()
    crawler_run_duration_seconds.labels(status=status, execution_mode=execution_mode).observe(duration_seconds)


def record_catalog_import(outcome, duration_seconds):
    catalog_import_requests_total.labels(outcome=outcome).inc()
    catalog_import_duration_seconds.observe(duration_seconds)


def record_dump(mode, document_count):
    document_dump_requests_total.labels(mode=mode).inc()
    document_dump_document_count.observe(document_count)


def record_file_serve(outcome, mode, content_type, duration_seconds):
    normalized_type = (content_type or 'unknown').replace('/', '_')
    file_serve_requests_total.labels(
        outcome=outcome,
        mode=mode,
        content_type=normalized_type,
    ).inc()
    file_serve_duration_seconds.labels(mode=mode).observe(duration_seconds)