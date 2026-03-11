# Backend Changes — Azure Deployment

## Overview

Deployed the Django backend to an Azure VM (Ubuntu 24.04) at **52.140.125.36**, served via Gunicorn + Nginx on port 80. Imported the real RDSO catalog (3011 documents, 358 subheads, 30 categories) and configured PDF file serving from the Azure filesystem.

---

## Azure VM Setup

- **OS:** Ubuntu 24.04 LTS
- **IP:** 52.140.125.36
- **Python:** 3.12
- **App path:** `/home/pharmagaurd/RDSO/BackRail/backend/app`
- **Media files:** `/home/pharmagaurd/RDSO/media/RDSO/` (copied from local `D:\RDSO` via SCP)

### Gunicorn (systemd service: `backrail`)

- Workers: 4
- Bind: `127.0.0.1:7146`
- Working directory: `/home/pharmagaurd/RDSO/BackRail/backend/app`
- Managed via: `sudo systemctl restart backrail`

### Nginx (`/etc/nginx/sites-enabled/backrail`)

- Listens on port **80**
- Proxies all requests to Gunicorn at `127.0.0.1:7146`
- Serves `/static/` from `/home/pharmagaurd/RDSO/BackRail/backend/app/staticfiles/`
- Serves `/media/` from `/home/pharmagaurd/RDSO/media/`
- `client_max_body_size 100M`
- Config saved locally as `nginx_backrail.conf`

### .env (on Azure only, NOT committed)

```
DJANGO_SECRET_KEY=<secret>
DEBUG=False
ALLOWED_HOSTS=52.140.125.36,localhost,127.0.0.1
RDSO_STORAGE_ROOT=/home/pharmagaurd/RDSO/media/RDSO
```

---

## Backend Code Changes (`backend/app/app/settings.py`)

### 1. MEDIA_ROOT — pointed to Azure filesystem

```diff
- MEDIA_ROOT = BASE_DIR / 'media'
+ MEDIA_ROOT = Path('/home/pharmagaurd/RDSO/media')
```

### 2. RDSO_STORAGE_ROOT — default changed to Azure path

```diff
- RDSO_STORAGE_ROOT = Path(os.environ.get('RDSO_STORAGE_ROOT', r'D:\RDSO'))
+ RDSO_STORAGE_ROOT = Path(os.environ.get('RDSO_STORAGE_ROOT', '/home/pharmagaurd/RDSO/media/RDSO'))
```

Both of these can be overridden by setting `RDSO_STORAGE_ROOT` in `.env`.

### 3. CORS — always permissive (replaces conditional block)

The old conditional block (permissive in DEBUG, restrictive otherwise) was replaced:

```diff
- if DEBUG:
-     CORS_ALLOW_ALL_ORIGINS = True
- else:
-     CORS_ALLOW_ALL_ORIGINS = False
-     CORS_ALLOWED_ORIGINS = [...]
+ CORS_ALLOW_ALL_ORIGINS = True
+ CORS_ALLOW_CREDENTIALS = True
+ CORS_ALLOW_HEADERS = ['*']
+ CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']
+ CORS_EXPOSE_HEADERS = ['*']
```

> **Note:** This should be tightened once a domain name / HTTPS is configured.

---

## Data Import

Ran `python manage.py import_rdso_catalog --clear` on Azure using:

- `catalog_flat.json` — flat catalog of all RDSO documents
- `__state__.json` — maps document IDs to file paths on disk

**Result:** 30 categories, 358 subheads, 3011 documents imported into SQLite DB.

---

## Frontend Changes (Flutter)

### `lib/config/api_config.dart`

Default API base URL changed to point at the Azure VM:

```diff
- defaultValue: 'http://localhost:8000/api',
+ defaultValue: 'http://52.140.125.36/api',
```

### Stability & coherence refactor (16 files)

The following Flutter files were modified as part of an earlier stability refactor (error handling, navigation, service layer improvements):

- `lib/main.dart` — app initialization cleanup
- `lib/screens/admin/crawler_screen.dart`
- `lib/screens/category_results_screen.dart` — simplified
- `lib/screens/drawing_list_screen.dart` — simplified
- `lib/screens/home_dashboard.dart` — streamlined
- `lib/screens/login_screen.dart`
- `lib/screens/register_screen.dart`
- `lib/screens/subhead_list_screen.dart`
- `lib/services/admin_service.dart` — improved error handling
- `lib/services/api_service.dart` — added helpers
- `lib/services/catalog_service.dart`
- `lib/services/document_service.dart`
- `lib/services/notification_service.dart`
- `lib/services/post_service.dart`
- `lib/utils/pdf_helper_native.dart`
- `lib/widgets/app_drawer.dart` — streamlined

### New files

- `lib/config/routes.dart` — centralized route definitions
- `lib/utils/category_icons.dart` — category icon mapping
- `lib/utils/download_helper.dart` — download utility

---

## Verification

- **Auth:** `POST /api/auth/login/` with ADMIN01 credentials → 200 OK + JWT tokens
- **Categories:** `GET /api/categories/` → 30 real categories returned
- **Documents:** `GET /api/documents/` → 3026 documents (paginated)
- **PDF download:** `GET /api/documents/100/file/` → 200 OK, 2.7 MB PDF (BA-11404)
