# BackRail — HRMS Document Management & Feedback API

A Django REST Framework backend for railway HRMS (Human Resource Management System) document management, user registration workflows, and collaborative feedback.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running the Server](#running-the-server)
- [API Endpoints](#api-endpoints)
  - [Authentication](#authentication)
  - [User Profile](#user-profile)
  - [Admin — User Management](#admin--user-management)
  - [Documents](#documents)
  - [Posts & Feedback](#posts--feedback)
  - [Batch Actions](#batch-actions)
  - [Data Sync (Dump)](#data-sync-dump)
  - [Audit Logs](#audit-logs)
  - [API Docs (Swagger)](#api-docs-swagger)
- [Authentication Flow](#authentication-flow)
- [Running Tests](#running-tests)
- [License](#license)

---

## Features

- **User Registration & Approval Workflow** — New users register with an HRMS ID and remain in `pending` status until an admin approves or rejects them.
- **JWT Authentication** — Access tokens (5 min) + refresh tokens (30 days) via `simplejwt`. Only `accepted` users can obtain tokens.
- **Role-Based Access Control** — Endpoints are gated by `IsAcceptedUser` (regular users) or `IsAdminUser` (staff/superusers).
- **Document Management** — Admins create documents with categories; accepted users can list and view them.
- **Posts & Feedback** — Users can post comments or feedback against documents, with nested reply support.
- **Batch Action Queue** — Offline-first clients can sync multiple actions (comments/feedback) in a single request.
- **Incremental Data Dump** — `GET /api/dump/` supports a `last_synced` timestamp to fetch only updated documents.
- **Audit Logging** — Every login, status change, document creation, download, and post is recorded in `AuditLog`.
- **Swagger / OpenAPI** — Auto-generated docs via `drf-spectacular`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.2 / Django REST Framework 3.16 |
| Auth | `djangorestframework-simplejwt` (JWT) |
| CORS | `django-cors-headers` |
| API Docs | `drf-spectacular` (OpenAPI 3 / Swagger UI) |
| Database | SQLite (development) |
| PDF Tools | `reportlab`, `pypdf`, `pillow` (for future watermarking) |
| Logging | `colorlog` (coloured console output) |

---

## Project Structure

```
RailWay/
├── backend/
│   └── app/                        # Django project root (manage.py lives here)
│       ├── app/                    # Project settings package
│       │   ├── settings.py
│       │   ├── urls.py
│       │   ├── wsgi.py
│       │   └── asgi.py
│       └── users/                  # Main application
│           ├── models.py           # User, Document, Category, Post, AuditLog
│           ├── serializers.py      # DRF serializers
│           ├── auth_serializers.py # Custom JWT token serializer
│           ├── views.py            # All API views
│           ├── urls.py             # Route definitions
│           ├── permissions.py      # IsAcceptedUser permission class
│           ├── admin.py            # Django admin registrations
│           ├── tests.py            # 91 comprehensive tests
│           └── migrations/
├── requirements.txt
├── ENDPOINTS_TODO.md               # Implementation checklist
├── _api_test.ipynb                 # Jupyter notebook for manual API testing
└── .gitignore
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/IAteNoodles/BackRail.git
cd BackRail

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

# Admin superuser credentials (also used by tests)
HRMS_ID=1
password=your-admin-password
```

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key for cryptographic signing |
| `DEBUG` | No | `True` for development (defaults to `False`) |
| `HRMS_ID` | No | Admin HRMS ID used by the test suite |
| `password` | No | Admin password used by the test suite |

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

### Running the Server

```bash
cd backend/app
python manage.py runserver
```

The API will be available at `http://localhost:8000/api/`.

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
| `GET` | `/api/documents/?download=true` | Accepted User | Request document download (returns 501 — not yet implemented) |

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
