from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .serializers import CategorySerializer, DocumentSerializer, SubheadSerializer
from .models import Category, Document, Subhead


def _parse_diff_flag(diff_value):
    if diff_value is None:
        return True

    normalized = str(diff_value).strip().lower()
    if normalized in {'1', 'true', 'yes'}:
        return True
    if normalized in {'0', 'false', 'no'}:
        return False
    raise ValueError('diff must be one of true/false, 1/0, or yes/no.')


def build_dump_payload(last_synced=None, diff_value=None):
    use_diff = _parse_diff_flag(diff_value)
    parsed_last_synced = parse_datetime(last_synced) if last_synced else None

    if last_synced and parsed_last_synced is None:
        raise ValueError('last_synced must be a valid ISO-8601 timestamp.')

    documents = Document.objects.all()
    mode = 'full'
    if use_diff and parsed_last_synced is not None:
        documents = documents.filter(last_updated__gt=parsed_last_synced)
        mode = 'incremental'

    categories = Category.objects.all()
    subheads = Subhead.objects.all()

    return {
        'documents': DocumentSerializer(documents, many=True).data,
        'categories': CategorySerializer(categories, many=True).data,
        'subheads': SubheadSerializer(subheads, many=True).data,
        'timestamp': timezone.now().isoformat(),
        'mode': mode,
        'filters': {
            'last_synced': last_synced,
            'diff': use_diff,
        },
        'document_count': documents.count(),
    }