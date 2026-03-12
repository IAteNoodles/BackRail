# RDSO Document Management System

A full-stack railway HRMS document management system with a Django REST API backend and Flutter cross-platform frontend (Web, Windows, Android).

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start — Deploy Script](#quick-start--deploy-script)
- [Manual Setup](#manual-setup)
  - [Prerequisites](#prerequisites)
  - [Backend Installation](#backend-installation)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running the Backend](#running-the-backend)
- [Frontend (Flutter)](#frontend-flutter)
  - [Running on Web](#running-on-web)
  - [Building for Windows](#building-for-windows)
  - [Building for Android](#building-for-android)
- [API Endpoints](#api-endpoints)
  - [Authentication](#authentication)
  - [User Profile](#user-profile)
  - [Admin — User Management](#admin--user-management)
  - [Documents](#documents)
  - [PDF Viewing & Download](#pdf-viewing--download)
  - [Posts & Feedback](#posts--feedback)
  - [Batch Actions](#batch-actions)
  - [Data Sync (Dump)](#data-sync-dump)
  - [Audit Logs](#audit-logs)
  - [API Docs (Swagger)](#api-docs-swagger)
- [Authentication Flow](#authentication-flow)
- [Deployment](#deployment)
- [Running Tests](#running-tests)
- [License](#license)

---

## Features

- **User Registration & Approval Workflow** — New users register with an HRMS ID and remain in `pending` status until an admin approves or rejects them.
- **JWT Authentication** — Access tokens (5 min) + refresh tokens (30 days) via `simplejwt`. Only `accepted` users can obtain tokens.
- **Role-Based Access Control** — Endpoints are gated by `IsAcceptedUser` (regular users) or `IsAdminUser` (staff/superusers).
- **Document Management** — Admins create documents with categories; accepted users can list and view them.
- **PDF Viewing & Watermarked Download** — In-app PDF viewer with watermarked downloads stamped with user's HRMS ID and timestamp.
- **Posts & Feedback** — Users can post comments or feedback against documents, with nested reply support.
- **Batch Action Queue** — Offline-first clients can sync multiple actions (comments/feedback) in a single request.
- **Data Dump Contract** — `GET /api/dump/` supports full or incremental sync, including `diff=false` to force a full dump even when `last_synced` is present.
- **Audit Logging** — Every login, status change, document creation, download, and post is recorded in `AuditLog`.
- **Admin Dashboard** — Admin screens for user management, audit logs, and document administration.
- **Cross-Platform Frontend** — Flutter app runs on Web (Chrome), Windows, and Android.
- **Swagger / OpenAPI** — Auto-generated docs via `drf-spectacular`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 / Django REST Framework 3.16 |
| Auth | `djangorestframework-simplejwt` (JWT) |
| CORS | `django-cors-headers` |
| API Docs | `drf-spectacular` (OpenAPI 3 / Swagger UI) |
| Metrics | `django-prometheus` + Prometheus scrape endpoint |
| Database | SQLite (development) |
| PDF Tools | `reportlab` (generation), `pypdf` (watermarking), `pillow` |
| Production Server | `waitress` (Windows) / `gunicorn` (Linux/macOS) |
| Frontend | Flutter (Dart) — Web, Windows, Android |
| UI Kit | `ux4g` design system |
| Logging | `colorlog` locally, structured JSON logs in production for Loki |

---

## Project Structure

```
rdso_documents_frontend/
├── RailWay/
│   ├── deploy.py                   # One-command deployment script
│   ├── requirements.txt            # Python dependencies
│   ├── README.md
│   ├── backend/
│   │   └── app/                    # Django project root
│   │       ├── app/                # Project settings
│   │       │   ├── settings.py
│   │       │   ├── urls.py
│   │       │   ├── wsgi.py
│   │       │   └── asgi.py
│   │       ├── users/              # Main application
│   │       │   ├── models.py       # User, Document, Category, Post, AuditLog
│   │       │   ├── serializers.py
│   │       │   ├── views.py
│   │       │   ├── urls.py
│   │       │   ├── permissions.py
│   │       │   └── management/     # Custom commands (populate_mock_data)
│   │       ├── media/documents/    # Generated PDF files
│   │       └── db.sqlite3
│   └── stable-env/                 # Python virtual environment
├── lib/                            # Flutter frontend source
│   ├── main.dart
│   ├── config/
│   │   └── api_config.dart         # Backend URL configuration
│   ├── models/                     # Data models (User, Document, Post, etc.)
│   ├── services/                   # API services (auth, documents, posts, etc.)
│   ├── screens/                    # UI screens
│   │   ├── login_screen.dart
│   │   ├── register_screen.dart
│   │   ├── home_dashboard.dart
│   │   ├── category_results_screen.dart
│   │   ├── pdf_view_screen.dart
│   │   ├── notifications_screen.dart
│   │   └── admin/                  # Admin-only screens
│   ├── widgets/                    # Reusable widgets
│   └── utils/                      # Platform-specific helpers
├── pubspec.yaml                    # Flutter dependencies
├── android/                        # Android build config
├── windows/                        # Windows build config
└── web/                            # Web build config
```

---

## Quick Start — Deploy Script

The fastest way to get the backend running:

```bash
cd RailWay

# Full setup + production server
python deploy.py

# Development mode (DEBUG=True, Django runserver)
python deploy.py --dev

# Run Redis-backed crawler worker (Linux/macOS deployment path)
python deploy.py --run-worker --worker-queue crawler

# Setup only (install deps, migrate, collect static)
python deploy.py --setup

# Run server only (after setup)
python deploy.py --run --port 8000

# Populate mock data (test users, documents, PDFs)
python deploy.py --populate

# Bind to a specific host/port
python deploy.py --host 0.0.0.0 --port 8000
```

### Deploy Script Options

| Flag | Description |
|---|---|
| `--setup` | Setup only: create venv, install deps, migrate, collect static |
| `--run` | Run server only (skip setup) |
| `--run-worker` | Run the django-rq worker for a queue (Linux/macOS path) |
| `--populate` | Populate mock data and exit |
| `--dev` | Development mode (DEBUG=True, Django runserver) |
| `--host` | Host to bind (default: `0.0.0.0`) |
| `--port` | Port to bind (default: `8000`) |
| `--worker-queue` | Queue name used with `--run-worker` (default: `crawler`) |

### Test Credentials (after `--populate`)

| HRMS ID | Password | Role |
|---|---|---|
| `ADMIN01` | `admin123pass` | Superuser / Admin |
| `EMP1001` | `emp1001pass` | Accepted User |
| `EMP1002` | `emp1002pass` | Pending User |
| `EMP1003` | `emp1003pass` | Rejected User |

---

## Manual Setup

### Prerequisites

- Python 3.10+
- pip
- Flutter SDK 3.10+ (for frontend builds)

### Backend Installation

```bash
# Clone the repository
git clone https://github.com/IAteNoodles/railways.git
cd railways/rdso_documents_frontend/RailWay

# Create and activate a virtual environment
python -m venv stable-env

# Windows
stable-env\Scripts\activate
# macOS / Linux
source stable-env/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file inside `backend/app/`:

```env
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
APP_ENV=production
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=https://app.example.com
CSRF_TRUSTED_ORIGINS=https://app.example.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
LOG_JSON=True

# Admin superuser credentials (also used by tests)
HRMS_ID=1
password=your-admin-password
REDIS_URL=redis://127.0.0.1:6379/0
PROMETHEUS_METRICS_ENABLED=True
PROMETHEUS_METRICS_PATH=metrics/
```

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key for cryptographic signing |
| `DEBUG` | No | `True` for development (defaults to `False`) |
| `ALLOWED_HOSTS` | No | Comma-separated Django allowed hosts list |
| `APP_ENV` | No | Deployment mode used for production security and logging defaults (`development` or `production`) |
| `CORS_ALLOW_ALL_ORIGINS` | No | `True` keeps the backend permissive; set `False` to enforce `CORS_ALLOWED_ORIGINS` |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated allowed origins used when `CORS_ALLOW_ALL_ORIGINS=False` |
| `CSRF_TRUSTED_ORIGINS` | No | Comma-separated trusted HTTPS origins for Django CSRF validation |
| `HRMS_ID` | No | Admin HRMS ID used by the test suite |
| `password` | No | Admin password used by the test suite |
| `REDIS_URL` | No | Redis connection string for upcoming crawler, cache, and sync work |
| `DJANGO_RQ_ENABLED` | No | Enables django-rq integration where the platform supports it |
| `CRAWLER_USE_QUEUE` | No | Enables queue-backed crawler execution instead of thread fallback |
| `PROMETHEUS_METRICS_ENABLED` | No | Enables the Prometheus scrape endpoint (defaults to `True`) |
| `PROMETHEUS_METRICS_PATH` | No | Relative URL path for the metrics endpoint (defaults to `metrics/`) |
| `LOG_JSON` | No | Emits JSON logs for Loki and Promtail ingestion; defaults to `True` in production |
| `LOG_LEVEL` | No | Root application log level (defaults to `INFO`) |
| `SECURE_SSL_REDIRECT` | No | Forces HTTPS redirects in production |

### Monitoring

- Prometheus metrics are exposed at `/metrics/` by default.
- `django-prometheus` instruments Django request and database activity automatically.
- The backend also exposes custom application metrics for crawler launch attempts, crawler log throughput, catalog import duration, dump request volume, and file serving outcomes.
- In a multi-process deployment such as Gunicorn, configure Prometheus multiprocess collection before relying on aggregated worker metrics.
- Production logging now emits request-aware JSON records that are ready for Loki via Promtail.

Production note:

- The current default remains permissive for CORS to preserve compatibility, but the backend now supports environment-driven tightening without code changes.

### Worker Deployment

- The crawler endpoints can now persist run state and use Redis-backed queue execution when `DJANGO_RQ_ENABLED=True` and `CRAWLER_USE_QUEUE=True`.
- On Windows and during tests, the backend intentionally falls back to thread mode so startup and local development remain stable.
- For Linux deployment, use `python deploy.py --run-worker --worker-queue crawler` or a systemd service based on [RailWay/monitoring/backrail-rqworker.service.example](RailWay/monitoring/backrail-rqworker.service.example).

### Monitoring Deployment Assets

- Example Prometheus scrape config: [RailWay/monitoring/prometheus.yml](RailWay/monitoring/prometheus.yml)
- Example Loki config: [RailWay/monitoring/loki-config.yml](RailWay/monitoring/loki-config.yml)
- Example Promtail config: [RailWay/monitoring/promtail-config.yml](RailWay/monitoring/promtail-config.yml)
- Example worker service: [RailWay/monitoring/backrail-rqworker.service.example](RailWay/monitoring/backrail-rqworker.service.example)
- Example web service: [RailWay/monitoring/backrail-web.service.example](RailWay/monitoring/backrail-web.service.example)
- Example Loki service: [RailWay/monitoring/loki.service.example](RailWay/monitoring/loki.service.example)
- Example Promtail service: [RailWay/monitoring/promtail.service.example](RailWay/monitoring/promtail.service.example)
- Example node exporter service: [RailWay/monitoring/node_exporter.service.example](RailWay/monitoring/node_exporter.service.example)
- Example redis exporter service: [RailWay/monitoring/redis_exporter.service.example](RailWay/monitoring/redis_exporter.service.example)
- Example Grafana dashboard: [RailWay/monitoring/grafana/backrail-overview.dashboard.json](RailWay/monitoring/grafana/backrail-overview.dashboard.json)

Recommended Linux VM deployment layout:

- `gunicorn` serves Django on `127.0.0.1:7146`
- `nginx` terminates TLS and proxies to Gunicorn
- `redis` backs cache and crawler queue state
- `prometheus` scrapes Django, Redis exporter, and node exporter
- `loki` stores logs and `promtail` ships journal entries for the web, worker, and nginx services

### Database Setup

```bash
cd backend/app
python manage.py migrate
python manage.py createsuperuser
```

When prompted by `createsuperuser`, enter your HRMS ID and password. Then manually set the superuser's status to `accepted`:

```bash
python manage.py shell -c "
from users.models import User
u = User.objects.get(is_superuser=True)
u.user_status = 'accepted'
u.save()
print(f'Superuser {u.HRMS_ID} is now accepted.')
"
```

### Running the Backend

```bash
cd backend/app
python manage.py runserver
```

The API will be available at `http://localhost:8000/api/`.

---

## Frontend (Flutter)

The frontend is a Flutter app in the workspace root (`rdso_documents_frontend/`).

### API Configuration

Edit `lib/config/api_config.dart` to set the backend URL:

```dart
class ApiConfig {
  static String get baseUrl {
    if (kIsWeb) return 'http://<YOUR_SERVER_IP>:8000/api';
    if (Platform.isAndroid) return 'http://<YOUR_SERVER_IP>:8000/api';
    return 'http://<YOUR_SERVER_IP>:8000/api';
  }
}
```

### Running on Web

```bash
cd rdso_documents_frontend
flutter pub get
flutter run -d chrome --web-port=9090 --web-hostname=0.0.0.0
```

### Building for Windows

```bash
flutter build windows --release
```

Output: `build\windows\x64\runner\Release\`

### Building for Android

```bash
flutter build apk --release
```

Output: `build\app\outputs\flutter-apk\app-release.apk`

---

## API Endpoints

All endpoints are prefixed with `/api/`.

### Authentication

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/register/` | None | Register a new user (status defaults to `pending`) |
| `POST` | `/api/login/` | None | Obtain JWT access + refresh tokens (accepted users only) |
| `POST` | `/api/refresh/` | None | Refresh an expired access token |

**Register — Request Body:**
```json
{
  "HRMS_ID": "12345",
  "password": "securepass",
  "email": "user@example.com",
  "phone_number": "9876543210"
}
```
> `email` and `phone_number` are optional. Phone must be exactly 10 digits.

**Login — Request Body:**
```json
{
  "HRMS_ID": "12345",
  "password": "securepass"
}
```

**Login — Response:**
```json
{
  "access": "<jwt-access-token>",
  "refresh": "<jwt-refresh-token>"
}
```

### User Profile

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/hello/` | Accepted User | Returns the authenticated user's profile |

### Admin — User Management

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/registrations/` | Admin | List all users (optional `?filter=pending\|accepted\|rejected`) |
| `POST` | `/api/update_status/` | Admin | Accept or reject a user |

**Update Status — Request Body:**
```json
{
  "HRMS_ID": "12345",
  "status": "accepted"
}
```
> `status` must be `"accepted"` or `"rejected"`.

### Documents

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/create_document/` | Admin | Create a new document with optional categories |
| `GET` | `/api/documents/` | Accepted User | List documents (optional `?document_ids=DOC-1,DOC-2`) |

**Create Document — Request Body:**
```json
{
  "document_id": "DOC-001",
  "name": "Safety Manual",
  "version": "2.0",
  "link": "https://example.com/doc",
  "internal_link": "https://internal.example.com/doc",
  "category_names": ["Safety", "Procedures"]
}
```
> Categories are created automatically if they don't already exist.

### PDF Viewing & Download

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/documents/<document_id>/pdf/` | Accepted User | View PDF inline |
| `GET` | `/api/documents/<document_id>/pdf/?download=true` | Accepted User | Download watermarked PDF |

The download endpoint stamps each PDF with: `Downloaded by <HRMS_ID> at <timestamp>`.

### Posts & Feedback

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/create_post/` | Accepted User | Create a comment or feedback on a document |
| `GET` | `/api/posts/?document_id=DOC-1` | Accepted User | List all posts for a document |
| `GET` | `/api/feedback/<document_id>/` | Accepted User | List only feedback-type posts for a document |

**Create Post — Request Body:**
```json
{
  "post_type": "comment",
  "content": "This section needs a revision.",
  "document_id": "DOC-001",
  "parent": null
}
```
> `post_type` is `"comment"` or `"feedback"`. Set `parent` to a post ID to create a reply.

### Batch Actions

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/actions/batch/` | Accepted User | Submit multiple comments/feedback in one request |

**Request Body:**
```json
{
  "actions": [
    { "type": "comment", "content": "Batch item 1", "document_id": "DOC-001" },
    { "type": "feedback", "content": "Batch item 2", "document_id": "DOC-001", "parent": null }
  ]
}
```

**Response:**
```json
{
  "results": [
    { "index": 0, "status": "ok", "id": 1 },
    { "index": 1, "status": "ok", "id": 2 }
  ]
}
```
> Each action is processed independently — partial failures are reported per-item.

### Data Sync (Dump)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/dump/` | Accepted User | Full dump of documents and categories |
| `GET` | `/api/dump/?last_synced=<ISO-timestamp>` | Accepted User | Incremental dump (only documents updated after the given timestamp) |
| `GET` | `/api/dump/?last_synced=<ISO-timestamp>&diff=false` | Accepted User | Forced full dump while preserving the client timestamp parameter |

Response notes:

- `mode` is `full` or `incremental`.
- `filters.last_synced` echoes the request value.
- `filters.diff` reflects the parsed diff mode.
- `document_count` exposes the number of documents included in the response.

### Audit Logs

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/logs/documents/` | Admin | All document-related audit logs (newest first) |
| `GET` | `/api/logs/users/` | Admin | All user-related audit logs (newest first) |

### API Docs (Swagger)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/schema/` | OpenAPI 3.0 schema (JSON/YAML) |
| `GET` | `/api/docs/` | Swagger UI |

---

## Authentication Flow

```
┌──────────┐       POST /api/register/        ┌──────────┐
│  Client   │ ──────────────────────────────►  │  Server  │
│           │  { HRMS_ID, password, ... }      │          │
│           │  ◄────────────────────────────── │          │
│           │  201 { user_status: "pending" }  │          │
└──────────┘                                   └──────────┘
     │                                              │
     │         Admin approves via                    │
     │         POST /api/update_status/              │
     │                                              │
┌──────────┐       POST /api/login/           ┌──────────┐
│  Client   │ ──────────────────────────────►  │  Server  │
│           │  { HRMS_ID, password }           │          │
│           │  ◄────────────────────────────── │          │
│           │  200 { access, refresh }         │          │
└──────────┘                                   └──────────┘
     │                                              │
     │  Authorization: Bearer <access>              │
     │  GET /api/hello/                             │
     │  GET /api/documents/                         │
     │  POST /api/create_post/                      │
     │  ...                                         │
```

1. User registers → status is `pending`.
2. Admin reviews and sets status to `accepted` or `rejected`.
3. Only `accepted` users can log in and receive JWT tokens.
4. Access token (5 min) is sent in the `Authorization: Bearer` header.
5. Refresh token (30 days) is used at `/api/refresh/` to get a new access token.

---

## Deployment

### Production Backend

```bash
cd RailWay
python deploy.py --host 0.0.0.0 --port 8000
```

This uses **waitress** (Windows) or **gunicorn** (Linux/macOS) as a production WSGI server.

### Network Access

To access from other devices on your LAN:

1. Find your IP: `ipconfig` (Windows) or `ip addr` (Linux)
2. Update `lib/config/api_config.dart` with your IP
3. Start backend: `python deploy.py --host 0.0.0.0 --port 8000`
4. Start frontend: `flutter run -d chrome --web-port=9090 --web-hostname=0.0.0.0`
5. Access from other devices at `http://<YOUR_IP>:9090`

---

## Running Tests

The test suite contains **91 tests** covering registration, login, token refresh, CRUD operations, batch actions, audit logging, permission enforcement, and security edge cases.

```bash
cd backend/app
python manage.py test users -v2
```

> Tests use their own database and read admin credentials from the `.env` file.

---

## License

This project is for internal use. See the repository owner for licensing details.
