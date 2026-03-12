# 📋 Project Backend Endpoints Checklist

This checklist tracks the implementation of backend services as described in the [BackRail V1-1.pdf](BackRail%20V1-1.pdf) documentation.

## 🔐 Authentication & Session Management
- [x] **User Registration** (`POST /register`)
  - [x] Implement registration with optional email and default `PENDING` status.
  - [x] Fields: `Name`, `HRMS_ID`, `Password`, `Email` (Optional), `Phone` (Optional).
- [x] **User Login** (`POST /login`)
  - [x] Implement credential verification and account status check (Pending, Approved, Rejected).
  - [x] Return JWT Access Token + Refresh Token for approved accounts.
- [x] **Token Refresh** (`POST /refresh`)
  - [x] Implement session refresh logic (30-day expiry for refresh tokens).

## 🔄 Data Synchronization (Offline Support)
- [x] **Metadata Dump** (`GET /dump`)
  - [x] Incremental dump based on `last_synced` timestamp.
  - [x] Full dump mode (`diff=false`) to force a full sync even when `last_synced` is provided.
- [x] **Action Queue Synchronization** (`POST /actions/batch`) *(Deprecated)*
  - [x] Batch processing for client actions (Comments, Feedback) with per-item success/failure.
  - *Note: Kept for backward compatibility. Not actively used by frontend.*

## 📄 Secure Document Access
- [x] **Document Listing** (`GET /documents/`)
  - [x] List all documents with optional `document_ids` filter.
  - [x] Paginated responses.
- [x] **Document Streaming** (`GET /documents/?document_ids=X&download=false`)
  - [x] Raw PDF binary streaming for in-app viewing.
- [x] **Secure Download with Watermark** (`GET /documents/?document_ids=X&download=true`)
  - [x] PDF watermarking (User `HRMS_ID` + Server Timestamp) before streaming.

## 📂 Catalog Hierarchy
- [x] **Categories** (`GET /categories/`)
  - [x] List categories with subhead/drawing counts. Paginated.
- [x] **Subheads** (`GET /categories/<id>/subheads/`)
  - [x] List subheads under a category. Paginated.
- [x] **Documents by Subhead** (`GET /subheads/<id>/documents/`)
  - [x] List documents under a subhead. Paginated.

## 💬 Collaboration & Feedback
- [x] **Fetch Document Feedback** (`GET /feedback/<document_id>/`)
  - [x] Return chronological list of feedback. Paginated.
- [x] **Fetch Document Posts** (`GET /posts/?document_id=X`)
  - [x] Return posts for a document. Paginated.
- [x] **Submit Feedback/Comment** (`POST /create_post/`)
  - [x] Create comment or feedback with nested reply support.

## 🛠️ Administration Module
- [x] **User Listing** (`GET /registrations/`)
  - [x] List all users with optional `?filter=pending|accepted|rejected`. Paginated.
- [x] **User Approval Workflow** (`POST /update_status/`)
  - [x] Approve/Reject with status tracking and audit logging.
- [x] **Create Document** (`POST /create_document/`)
  - [x] Admin-only document creation with category linking.

## 📋 Logs & Auditing
- [x] **Document Logs** (`GET /logs/documents/`)
  - [x] Paginated document audit logs.
- [x] **User Activity Logs** (`GET /logs/users/`)
  - [x] Paginated user audit logs.

## 🕷️ Crawler Management (Admin)
- [x] **Run Crawler** (`POST /admin/run-crawler/`)
- [x] **Crawler Status** (`GET /admin/crawler-status/`)
- [x] **Crawler Logs** (`GET /admin/crawler-logs/`)
- [x] **Import Catalog** (`POST /admin/import-catalog/`)

## 🏥 Health
- [x] **Health Check** (`GET /health/`)

## 📖 API Documentation
- [x] **OpenAPI Schema** (`GET /schema/`)
- [x] **Swagger UI** (`GET /docs/`)
