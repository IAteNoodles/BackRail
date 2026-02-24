# 📋 Project Backend Endpoints Checklist

This checklist tracks the implementation of backend services as described in the [BackRail V1-1.pdf](BackRail%20V1-1.pdf) documentation.

## 🔐 Authentication & Session Management
- [ ] **User Registration** (`POST /register`)
  - [ ] Implement registration with optional email and default `PENDING` status.
  - [ ] Fields: `Name`, `HRMS_ID`, `Password`, `Email` (Optional).
- [ ] **User Login** (`POST /login`)
  - [ ] Implement credential verification and account status check (Pending, Approved, Rejected).
  - [ ] Return JWT Access Token + Refresh Token for approved accounts.
- [ ] **Token Refresh** (`POST /refresh`)
  - [ ] Implement session refresh logic (30-day expiry for refresh tokens).

## 🔄 Data Synchronization (Offline Support)
- [ ] **Metadata Dump** (`GET /dump`)
  - [ ] Implement full dump (`diff=false`) and incremental dump (`diff=true`) based on `last_synced_timestamp`.
- [x] **Action Queue Synchronization** (`POST /actions/batch`)
  - [ ] Implement batch processing for client actions (Comments, Feedback) with per-item success/failure state.

## 📄 Secure Document Access
- [ ] **Document Streaming** (`GET /view/document/{document_id}?download=false`)
  - [ ] Implement raw PDF binary streaming for in-app viewing.
- [ ] **Secure Download with Watermark** (`GET /view/document/{document_id}?download=true`)
  - [ ] Implement PDF watermarking (User `HRMS_ID` + Server Timestamp) before streaming binary. (Requires `pypdf` or similar library).

## 💬 Collaboration & Feedback
- [ ] **Fetch Document Feedback** (`GET /view/feedback/{document_id}`)
  - [ ] Return chronological list of feedback (Author Name, `HRMS_ID`, Timestamp, Comment Text).
- [ ] **Submit Feedback** 
  - [ ] Integrated through the `/actions/batch` endpoint.

## 🛠️ Administration Module
- [ ] **Pending User Retrieval** (`GET /admin/registrations`)
  - [ ] List all users with `PENDING` status.
- [ ] **User Approval Workflow** (`POST /admin/users/{user_id}/decision`)
  - [ ] Implement logic for Approve/Reject decisions with optional rejection reasons.

## 📋 Logs & Auditing
- [ ] **Document Logs** (`GET /admin/logs/documents`)
  - [ ] Filterable logs by `Document ID`, `User ID`, and `Time Range`.
- [ ] **User Activity Logs** (`GET /admin/logs/users`)
  - [ ] Filterable logs by `User ID` and `Time Range`.
