import json
import logging
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils.dateparse import parse_datetime

from users.models import Category, Subhead, Document

logger = logging.getLogger('users.import_rdso')


class Command(BaseCommand):
    help = 'Import RDSO catalog_flat.json into the database'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without writing to DB')
        parser.add_argument('--clear', action='store_true', help='Delete all crawler-imported documents first')

    def handle(self, *args, **options):
        root = Path(settings.RDSO_STORAGE_ROOT)
        catalog_path = root / 'catalog_flat.json'
        state_path = root / '__state__.json'

        if not catalog_path.exists():
            logger.error('catalog_flat.json not found at %s', catalog_path)
            self.stderr.write(self.style.ERROR(f'catalog_flat.json not found at {catalog_path}'))
            return

        logger.info('Reading catalog from %s', catalog_path)
        with open(catalog_path, 'r', encoding='utf-8') as f:
            catalog = json.load(f)

        # Build file-URL -> metadata lookup from __state__.json
        file_meta = {}
        if state_path.exists():
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            file_meta = state.get('files_by_url', {})

        logger.info('Loaded %d drawings, %d file entries from state', len(catalog), len(file_meta))
        self.stdout.write(f'Loaded {len(catalog)} drawings, {len(file_meta)} file entries from state')

        if options['dry_run']:
            cats = set()
            subs = set()
            for rec in catalog:
                cats.add(rec['category'])
                subs.add((rec['category'], rec['subhead']))
            self.stdout.write(self.style.SUCCESS(
                f'DRY RUN: {len(cats)} categories, {len(subs)} subheads, {len(catalog)} documents'))
            return

        if options['clear']:
            deleted, _ = Document.objects.filter(drawing_id__isnull=False).delete()
            logger.warning('Cleared %d crawler-imported documents', deleted)
            self.stdout.write(self.style.WARNING(f'Cleared {deleted} crawler-imported documents'))

        stats = {'cat_created': 0, 'sub_created': 0, 'doc_created': 0, 'doc_updated': 0}

        with transaction.atomic():
            for rec in catalog:
                cat, created = Category.objects.get_or_create(name=rec['category'])
                if created:
                    logger.info('Created category: %s', rec['category'])
                    stats['cat_created'] += 1

                # Parse crawler_id from storage_path, e.g. "__s179"
                crawler_id = ''
                sp = rec.get('storage_path', '')
                m = re.search(r'__s(\d+)', sp)
                if m:
                    crawler_id = f's{m.group(1)}'

                sub, created = Subhead.objects.get_or_create(
                    name=rec['subhead'],
                    category=cat,
                    defaults={'crawler_id': crawler_id},
                )
                if created:
                    logger.debug('Created subhead: %s -> %s', rec['category'], rec['subhead'])
                    stats['sub_created'] += 1

                # Find file metadata from the first file URL
                fm = {}
                for file_url in rec.get('files', []):
                    if file_url in file_meta:
                        fm = file_meta[file_url]
                        break

                drawing_id = rec['id']
                doc_defaults = {
                    'name': rec['file_name'],
                    'description': rec.get('description') or '',
                    'version': 'Current',
                    'link': rec.get('page_url') or '',
                    'internal_link': f'/api/documents/?document_ids={drawing_id}&download=false',
                    'storage_path': sp,
                    'file_name_on_disk': fm.get('stored_file') or '',
                    'content_type': fm.get('content_type') or 'application/pdf',
                    'file_size': fm.get('size'),
                    'sha256': fm.get('sha256') or '',
                    'source_url': rec.get('page_url') or '',
                    'source_file_url': (rec.get('files') or [''])[0] if rec.get('files') else '',
                    'is_archived': False,
                    'subhead': sub,
                }

                crawled_at = fm.get('downloaded_at')
                if crawled_at:
                    doc_defaults['crawled_at'] = parse_datetime(crawled_at)
                checked_at = fm.get('last_checked_at')
                if checked_at:
                    doc_defaults['last_checked_at'] = parse_datetime(checked_at)

                doc, created = Document.objects.update_or_create(
                    drawing_id=drawing_id,
                    defaults={'document_id': str(drawing_id), **doc_defaults},
                )
                doc.category.set([cat])

                if created:
                    logger.debug('Created document: %s (drawing_id=%d)', rec['file_name'], drawing_id)
                    stats['doc_created'] += 1
                else:
                    logger.debug('Updated document: %s (drawing_id=%d)', rec['file_name'], drawing_id)
                    stats['doc_updated'] += 1

            # Update subhead drawing_count caches
            for sub in Subhead.objects.annotate(cnt=Count('documents')):
                if sub.drawing_count != sub.cnt:
                    sub.drawing_count = sub.cnt
                    sub.save(update_fields=['drawing_count'])

        msg = (
            f"Import complete: "
            f"{stats['cat_created']} categories created, "
            f"{stats['sub_created']} subheads created, "
            f"{stats['doc_created']} documents created, "
            f"{stats['doc_updated']} documents updated"
        )
        logger.info(msg)
        self.stdout.write(self.style.SUCCESS(msg))
