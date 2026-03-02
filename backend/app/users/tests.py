"""
Comprehensive test suite for the RailWay HRMS API.

Uses admin credentials from .env (HRMS_ID="1", password="9678781811")
to create a fresh superuser in setUp() against the test database.

Run with:
    python manage.py test users -v2
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status as http_status

from users.models import User, Document, Category, Post, AuditLog

# ---------------------------------------------------------------------------
# Admin credentials loaded from .env
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

ADMIN_HRMS_ID = os.environ.get("HRMS_ID", "1")
ADMIN_PASSWORD = os.environ.get("password", "9678781811")


# ---------------------------------------------------------------------------
# Base mixin – shared helpers
# ---------------------------------------------------------------------------
class APITestMixin:
    """Provides common setUp helpers for every test class."""

    def _create_admin(self):
        """Create the admin super-user used throughout the suite."""
        self.admin = User.objects.create_superuser(
            HRMS_ID=ADMIN_HRMS_ID, password=ADMIN_PASSWORD,
        )
        self.admin.user_status = "accepted"
        self.admin.save()

    def _create_users(self):
        """Create regular users with different statuses."""
        self.accepted_user = User.objects.create_user(
            HRMS_ID="100", password="accepted1234",
        )
        self.accepted_user.user_status = "accepted"
        self.accepted_user.save()

        self.pending_user = User.objects.create_user(
            HRMS_ID="200", password="pending1234",
        )
        # pending is the default – no explicit save needed

        self.rejected_user = User.objects.create_user(
            HRMS_ID="300", password="rejected123",
        )
        self.rejected_user.user_status = "rejected"
        self.rejected_user.save()

    def _create_document(self, doc_id="DOC-1", name="Test Doc", version="1.0",
                         link="https://example.com/doc",
                         internal_link="https://internal.example.com/doc",
                         categories=None):
        doc = Document.objects.create(
            document_id=doc_id, name=name, version=version,
            link=link, internal_link=internal_link,
        )
        for cat_name in (categories or []):
            cat, _ = Category.objects.get_or_create(name=cat_name)
            doc.category.add(cat)
        return doc

    # -- auth helpers -------------------------------------------------------
    def _login(self, hrms_id, password):
        """Return (access, refresh) tokens for the given creds."""
        resp = self.client.post(
            reverse("login"),
            {"HRMS_ID": hrms_id, "password": password},
            format="json",
        )
        return resp.data.get("access"), resp.data.get("refresh")

    def _admin_client(self):
        """Return an APIClient authenticated as admin."""
        c = APIClient()
        access, _ = self._login(ADMIN_HRMS_ID, ADMIN_PASSWORD)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return c

    def _user_client(self, hrms_id="100", password="accepted1234"):
        """Return an APIClient authenticated as a regular accepted user."""
        c = APIClient()
        access, _ = self._login(hrms_id, password)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return c

    def _anon_client(self):
        """Return an unauthenticated APIClient."""
        return APIClient()


# ===================================================================
# A.  REGISTRATION TESTS
# ===================================================================
class RegistrationTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    # -- happy path ---------------------------------------------------------
    def test_register_valid_user(self):
        """POST /register/ with valid data -> 201, status=pending."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "999",
            "password": "strongpass1",
            "email": "new@example.com",
            "phone_number": "9876543210",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(resp.data["user_status"], "pending")
        self.assertTrue(User.objects.filter(HRMS_ID="999").exists())

    def test_register_minimal_fields(self):
        """Only HRMS_ID and password are required."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "998", "password": "strongpass1",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)

    # -- duplicates ---------------------------------------------------------
    def test_register_duplicate_hrms_id(self):
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "100", "password": "strongpass1",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email(self):
        User.objects.create_user(HRMS_ID="800", password="strongpass1",
                                 email="dup@example.com")
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "801", "password": "strongpass1",
            "email": "dup@example.com",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_phone(self):
        User.objects.create_user(HRMS_ID="802", password="strongpass1",
                                 phone_number="1234567890")
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "803", "password": "strongpass1",
            "phone_number": "1234567890",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    # -- missing / invalid fields -------------------------------------------
    def test_register_missing_hrms_id(self):
        resp = self.client.post(reverse("register"), {
            "password": "strongpass1",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_missing_password(self):
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "997",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_short_password(self):
        """Password with fewer than 8 characters -> 400."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "996", "password": "short",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_phone_letters(self):
        """Phone with letters -> 400."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "995", "password": "strongpass1",
            "phone_number": "abcdefghij",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_phone_short(self):
        """Phone with fewer than 10 digits -> 400."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "994", "password": "strongpass1",
            "phone_number": "12345",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_register_invalid_phone_long(self):
        """Phone with more than 10 digits -> 400."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "993", "password": "strongpass1",
            "phone_number": "12345678901",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)


# ===================================================================
# B.  LOGIN / TOKEN TESTS
# ===================================================================
class LoginTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    def test_login_accepted_user(self):
        """Accepted user gets access + refresh tokens."""
        resp = self.client.post(reverse("login"), {
            "HRMS_ID": ADMIN_HRMS_ID, "password": ADMIN_PASSWORD,
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_login_pending_user_blocked(self):
        """Pending user is denied tokens."""
        resp = self.client.post(reverse("login"), {
            "HRMS_ID": "200", "password": "pending1234",
        }, format="json")
        self.assertIn(resp.status_code, [
            http_status.HTTP_400_BAD_REQUEST,
            http_status.HTTP_401_UNAUTHORIZED,
        ])
        self.assertNotIn("access", resp.data)

    def test_login_rejected_user_blocked(self):
        """Rejected user is denied tokens."""
        resp = self.client.post(reverse("login"), {
            "HRMS_ID": "300", "password": "rejected123",
        }, format="json")
        self.assertIn(resp.status_code, [
            http_status.HTTP_400_BAD_REQUEST,
            http_status.HTTP_401_UNAUTHORIZED,
        ])

    def test_login_wrong_password(self):
        resp = self.client.post(reverse("login"), {
            "HRMS_ID": ADMIN_HRMS_ID, "password": "wrongpassword",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_user(self):
        resp = self.client.post(reverse("login"), {
            "HRMS_ID": "NONEXISTENT", "password": "anything123",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_login_creates_audit_log(self):
        """Successful login creates an audit log entry."""
        self.client.post(reverse("login"), {
            "HRMS_ID": ADMIN_HRMS_ID, "password": ADMIN_PASSWORD,
        }, format="json")
        self.assertTrue(
            AuditLog.objects.filter(
                action="user_login", target_id=ADMIN_HRMS_ID
            ).exists()
        )


# ===================================================================
# C.  TOKEN REFRESH TESTS
# ===================================================================
class TokenRefreshTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()

    def test_refresh_valid(self):
        _, refresh = self._login(ADMIN_HRMS_ID, ADMIN_PASSWORD)
        resp = self.client.post(reverse("token_refresh"), {
            "refresh": refresh,
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_refresh_invalid_token(self):
        resp = self.client.post(reverse("token_refresh"), {
            "refresh": "garbage.token.value",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)


# ===================================================================
# D.  HELLO / PROFILE TESTS
# ===================================================================
class HelloTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    def test_hello_authenticated(self):
        c = self._admin_client()
        resp = c.get(reverse("hello"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(resp.data["HRMS_ID"], ADMIN_HRMS_ID)

    def test_hello_returns_user_fields(self):
        c = self._admin_client()
        resp = c.get(reverse("hello"))
        for field in ["HRMS_ID", "email", "phone_number", "user_status"]:
            self.assertIn(field, resp.data)

    def test_hello_unauthenticated(self):
        resp = self._anon_client().get(reverse("hello"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_hello_password_not_exposed(self):
        """Password field must never be in the response."""
        c = self._admin_client()
        resp = c.get(reverse("hello"))
        self.assertNotIn("password", resp.data)


# ===================================================================
# E.  ADMIN - REGISTRATION LIST TESTS
# ===================================================================
class RegistrationListTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    def test_list_as_admin(self):
        c = self._admin_client()
        resp = c.get(reverse("registration-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(resp.data, list)
        # admin + 3 users = 4
        self.assertEqual(len(resp.data), 4)

    def test_filter_pending(self):
        c = self._admin_client()
        resp = c.get(reverse("registration-list"), {"filter": "pending"})
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        for u in resp.data:
            self.assertEqual(u["user_status"], "pending")

    def test_filter_accepted(self):
        c = self._admin_client()
        resp = c.get(reverse("registration-list"), {"filter": "accepted"})
        for u in resp.data:
            self.assertEqual(u["user_status"], "accepted")

    def test_filter_rejected(self):
        c = self._admin_client()
        resp = c.get(reverse("registration-list"), {"filter": "rejected"})
        for u in resp.data:
            self.assertEqual(u["user_status"], "rejected")

    def test_list_as_regular_user_forbidden(self):
        c = self._user_client()
        resp = c.get(reverse("registration-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_list_unauthenticated(self):
        resp = self._anon_client().get(reverse("registration-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)


# ===================================================================
# F.  ADMIN - UPDATE USER STATUS TESTS
# ===================================================================
class UpdateUserStatusTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    def test_accept_user(self):
        c = self._admin_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "200", "status": "accepted",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.pending_user.refresh_from_db()
        self.assertEqual(self.pending_user.user_status, "accepted")

    def test_reject_user(self):
        c = self._admin_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "100", "status": "rejected",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.accepted_user.refresh_from_db()
        self.assertEqual(self.accepted_user.user_status, "rejected")

    def test_invalid_status_value(self):
        c = self._admin_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "200", "status": "banana",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_user(self):
        c = self._admin_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "NONEXISTENT", "status": "accepted",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_as_regular_user_forbidden(self):
        c = self._user_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "200", "status": "accepted",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_creates_audit_log(self):
        c = self._admin_client()
        c.post(reverse("update-user-status"), {
            "HRMS_ID": "200", "status": "accepted",
        }, format="json")
        log = AuditLog.objects.filter(
            action="user_status_change", target_id="200"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata["old_status"], "pending")
        self.assertEqual(log.metadata["new_status"], "accepted")


# ===================================================================
# G.  DOCUMENT CREATION TESTS
# ===================================================================
class CreateDocumentTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()

    def test_create_document_as_admin(self):
        c = self._admin_client()
        resp = c.post(reverse("create-document"), {
            "document_id": "DOC-100",
            "name": "Test Document",
            "version": "1.0",
            "link": "https://example.com/doc100",
            "internal_link": "https://internal.example.com/doc100",
            "category_names": ["Safety", "Procedures"],
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        self.assertTrue(Document.objects.filter(document_id="DOC-100").exists())
        doc = Document.objects.get(document_id="DOC-100")
        self.assertEqual(doc.category.count(), 2)

    def test_create_document_as_regular_user_forbidden(self):
        c = self._user_client()
        resp = c.post(reverse("create-document"), {
            "document_id": "DOC-101",
            "name": "Test", "version": "1.0",
            "link": "https://example.com/d",
            "internal_link": "https://internal.example.com/d",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_create_document_duplicate_id(self):
        self._create_document("DOC-DUP")
        c = self._admin_client()
        resp = c.post(reverse("create-document"), {
            "document_id": "DOC-DUP",
            "name": "Dup", "version": "1.0",
            "link": "https://example.com/dup",
            "internal_link": "https://internal.example.com/dup",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_document_missing_fields(self):
        c = self._admin_client()
        resp = c.post(reverse("create-document"), {
            "document_id": "DOC-MISS",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_new_categories_created(self):
        c = self._admin_client()
        c.post(reverse("create-document"), {
            "document_id": "DOC-CAT1",
            "name": "Cat Test", "version": "1.0",
            "link": "https://example.com/cat",
            "internal_link": "https://internal.example.com/cat",
            "category_names": ["BrandNewCategory"],
        }, format="json")
        self.assertTrue(Category.objects.filter(name="BrandNewCategory").exists())

    def test_existing_categories_reused(self):
        Category.objects.create(name="Existing")
        c = self._admin_client()
        c.post(reverse("create-document"), {
            "document_id": "DOC-CAT2",
            "name": "Cat Test 2", "version": "1.0",
            "link": "https://example.com/cat2",
            "internal_link": "https://internal.example.com/cat2",
            "category_names": ["Existing"],
        }, format="json")
        self.assertEqual(Category.objects.filter(name="Existing").count(), 1)

    def test_creates_audit_log(self):
        c = self._admin_client()
        c.post(reverse("create-document"), {
            "document_id": "DOC-LOG",
            "name": "Log Test", "version": "1.0",
            "link": "https://example.com/log",
            "internal_link": "https://internal.example.com/log",
        }, format="json")
        self.assertTrue(
            AuditLog.objects.filter(
                action="document_create", target_id="DOC-LOG"
            ).exists()
        )


# ===================================================================
# H.  DOCUMENT LIST TESTS
# ===================================================================
class DocumentListTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc1 = self._create_document("DOC-A", "Doc A", "1.0")
        self.doc2 = self._create_document("DOC-B", "Doc B", "2.0")

    def test_list_all(self):
        c = self._user_client()
        resp = c.get(reverse("document-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_list_filtered(self):
        c = self._user_client()
        resp = c.get(reverse("document-list"), {"document_ids": "DOC-A"})
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["document_id"], "DOC-A")

    def test_download_returns_501(self):
        c = self._user_client()
        resp = c.get(reverse("document-list"), {"download": "true"})
        self.assertEqual(resp.status_code, http_status.HTTP_501_NOT_IMPLEMENTED)

    def test_creates_audit_logs_bulk(self):
        """Audit logs are only created for download operations, not plain list."""
        c = self._user_client()
        AuditLog.objects.all().delete()
        # Plain list should NOT create audit logs
        c.get(reverse("document-list"))
        logs = AuditLog.objects.filter(action="document_view")
        self.assertEqual(logs.count(), 0)
        # Download request SHOULD create audit logs
        c.get(reverse("document-list"), {"download": "true"})
        logs = AuditLog.objects.filter(action="document_view")
        self.assertEqual(logs.count(), 2)  # one per document

    def test_unauthenticated(self):
        resp = self._anon_client().get(reverse("document-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)


# ===================================================================
# I.  DUMP TESTS
# ===================================================================
class DumpTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-DUMP", categories=["CatA"])

    def test_dump_all(self):
        c = self._user_client()
        resp = c.get(reverse("dump"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIn("documents", resp.data)
        self.assertIn("categories", resp.data)
        self.assertIn("timestamp", resp.data)
        self.assertGreaterEqual(len(resp.data["documents"]), 1)

    def test_dump_with_last_synced(self):
        c = self._user_client()
        # Fetch with a future timestamp - should return nothing
        resp = c.get(reverse("dump"), {"last_synced": "2099-01-01T00:00:00Z"})
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data["documents"]), 0)

    def test_dump_unauthenticated(self):
        resp = self._anon_client().get(reverse("dump"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)


# ===================================================================
# J.  POST CREATION TESTS
# ===================================================================
class CreatePostTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-POST")

    def test_create_comment(self):
        c = self._user_client()
        resp = c.post(reverse("create-post"), {
            "post_type": "comment",
            "content": "This is a comment.",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(resp.data["post_type"], "comment")

    def test_create_feedback(self):
        c = self._user_client()
        resp = c.post(reverse("create-post"), {
            "post_type": "feedback",
            "content": "This is feedback.",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(resp.data["post_type"], "feedback")

    def test_create_post_with_parent(self):
        c = self._user_client()
        # Create parent post first
        parent_resp = c.post(reverse("create-post"), {
            "post_type": "comment", "content": "Parent",
            "document_id": "DOC-POST",
        }, format="json")
        parent_id = parent_resp.data["id"]
        # Create reply
        resp = c.post(reverse("create-post"), {
            "post_type": "comment", "content": "Reply",
            "document_id": "DOC-POST", "parent": parent_id,
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        self.assertEqual(resp.data["parent"], parent_id)

    def test_create_post_invalid_document(self):
        c = self._user_client()
        resp = c.post(reverse("create-post"), {
            "post_type": "comment", "content": "Test",
            "document_id": "NONEXISTENT-DOC",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_post_missing_content(self):
        c = self._user_client()
        resp = c.post(reverse("create-post"), {
            "post_type": "comment",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_create_post_unauthenticated(self):
        resp = self._anon_client().post(reverse("create-post"), {
            "post_type": "comment", "content": "Test",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_creates_audit_log(self):
        c = self._user_client()
        c.post(reverse("create-post"), {
            "post_type": "comment", "content": "Audit test",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertTrue(
            AuditLog.objects.filter(
                action="post_create", target_id="DOC-POST"
            ).exists()
        )

    def test_user_hrms_id_set_automatically(self):
        """User HRMS_ID in response comes from auth, not from payload."""
        c = self._user_client()
        resp = c.post(reverse("create-post"), {
            "post_type": "comment", "content": "Who am I?",
            "document_id": "DOC-POST",
        }, format="json")
        self.assertEqual(resp.data["user_hrms_id"], "100")


# ===================================================================
# K.  POST LIST TESTS
# ===================================================================
class PostListTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-PL")
        Post.objects.create(
            user=self.accepted_user, post_type="comment",
            content="Comment 1", document=self.doc,
        )
        Post.objects.create(
            user=self.accepted_user, post_type="feedback",
            content="Feedback 1", document=self.doc,
        )

    def test_list_by_document(self):
        c = self._user_client()
        resp = c.get(reverse("post-list"), {"document_id": "DOC-PL"})
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_missing_document_param(self):
        c = self._user_client()
        resp = c.get(reverse("post-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_list_empty_for_other_doc(self):
        self._create_document("DOC-OTHER")
        c = self._user_client()
        resp = c.get(reverse("post-list"), {"document_id": "DOC-OTHER"})
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)


# ===================================================================
# L.  FEEDBACK LIST TESTS
# ===================================================================
class FeedbackListTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-FB")
        Post.objects.create(
            user=self.accepted_user, post_type="feedback",
            content="Feedback A", document=self.doc,
        )
        Post.objects.create(
            user=self.accepted_user, post_type="comment",
            content="Comment (not feedback)", document=self.doc,
        )

    def test_feedback_only(self):
        c = self._user_client()
        resp = c.get(reverse("feedback-list", kwargs={"document_id": "DOC-FB"}))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["post_type"], "feedback")

    def test_nonexistent_document(self):
        c = self._user_client()
        resp = c.get(reverse("feedback-list", kwargs={"document_id": "NOPE"}))
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)


# ===================================================================
# M.  BATCH ACTIONS TESTS
# ===================================================================
class BatchActionTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-BATCH")

    def test_batch_valid(self):
        c = self._user_client()
        resp = c.post(reverse("actions-batch"), {
            "actions": [
                {"type": "comment", "content": "Batch 1", "document_id": "DOC-BATCH"},
                {"type": "feedback", "content": "Batch 2", "document_id": "DOC-BATCH"},
            ]
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "ok" for r in results))

    def test_batch_partial_failure(self):
        c = self._user_client()
        resp = c.post(reverse("actions-batch"), {
            "actions": [
                {"type": "comment", "content": "Good", "document_id": "DOC-BATCH"},
                {"type": "comment", "content": "Bad", "document_id": "NO-SUCH-DOC"},
            ]
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        results = resp.data["results"]
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[1]["status"], "error")

    def test_batch_empty(self):
        c = self._user_client()
        resp = c.post(reverse("actions-batch"), {
            "actions": [],
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_batch_not_list(self):
        c = self._user_client()
        resp = c.post(reverse("actions-batch"), {
            "actions": "not a list",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_batch_unauthenticated(self):
        resp = self._anon_client().post(reverse("actions-batch"), {
            "actions": [
                {"type": "comment", "content": "x", "document_id": "DOC-BATCH"}
            ],
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_batch_creates_audit_logs(self):
        c = self._user_client()
        AuditLog.objects.all().delete()
        c.post(reverse("actions-batch"), {
            "actions": [
                {"type": "comment", "content": "A1", "document_id": "DOC-BATCH"},
                {"type": "comment", "content": "A2", "document_id": "DOC-BATCH"},
            ],
        }, format="json")
        self.assertEqual(
            AuditLog.objects.filter(action="batch_action").count(), 2
        )


# ===================================================================
# N.  ADMIN - AUDIT LOG TESTS
# ===================================================================
class AuditLogViewTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-ALOG")
        # Create some audit entries
        AuditLog.objects.create(
            user=self.admin, action="document_create",
            target_type="document", target_id="DOC-ALOG",
        )
        AuditLog.objects.create(
            user=self.admin, action="user_status_change",
            target_type="user", target_id="200",
        )

    def test_document_logs_as_admin(self):
        c = self._admin_client()
        resp = c.get(reverse("document-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        for log in resp.data:
            self.assertEqual(log["target_type"], "document")

    def test_document_logs_as_regular_user_forbidden(self):
        c = self._user_client()
        resp = c.get(reverse("document-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_user_logs_as_admin(self):
        c = self._admin_client()
        resp = c.get(reverse("user-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        for log in resp.data:
            self.assertEqual(log["target_type"], "user")

    def test_user_logs_unauthenticated(self):
        resp = self._anon_client().get(reverse("user-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_document_logs_ordered_newest_first(self):
        c = self._admin_client()
        resp = c.get(reverse("document-logs"))
        if len(resp.data) >= 2:
            self.assertGreaterEqual(
                resp.data[0]["created_at"], resp.data[1]["created_at"]
            )


# ===================================================================
# O.  SECURITY EDGE CASE TESTS
# ===================================================================
class SecurityTests(APITestMixin, TestCase):
    def setUp(self):
        self._create_admin()
        self._create_users()
        self.doc = self._create_document("DOC-SEC")

    # -- tampered / expired tokens ------------------------------------------
    def test_tampered_token_rejected(self):
        access, _ = self._login(ADMIN_HRMS_ID, ADMIN_PASSWORD)
        # Flip the last character
        tampered = access[:-1] + ("A" if access[-1] != "A" else "B")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered}")
        resp = c.get(reverse("hello"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_empty_bearer_token(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer ")
        resp = c.get(reverse("hello"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_no_auth_header(self):
        c = APIClient()
        resp = c.get(reverse("hello"))
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    # -- wrong HTTP methods -------------------------------------------------
    def test_get_on_register_not_allowed(self):
        resp = self.client.get(reverse("register"))
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_get_on_login_not_allowed(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_post_on_hello_not_allowed(self):
        c = self._admin_client()
        resp = c.post(reverse("hello"), {}, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_on_documents_not_allowed(self):
        c = self._admin_client()
        resp = c.delete(reverse("document-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_on_create_document_not_allowed(self):
        c = self._admin_client()
        resp = c.put(reverse("create-document"), {}, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_on_create_post_not_allowed(self):
        c = self._admin_client()
        resp = c.delete(reverse("create-post"))
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_on_update_status_not_allowed(self):
        c = self._admin_client()
        resp = c.put(reverse("update-user-status"), {}, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_405_METHOD_NOT_ALLOWED)

    # -- permission escalation attempts -------------------------------------
    def test_regular_user_cannot_create_document(self):
        c = self._user_client()
        resp = c.post(reverse("create-document"), {
            "document_id": "HACK-DOC", "name": "Hack",
            "version": "1.0", "link": "https://x.com",
            "internal_link": "https://x.com",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_regular_user_cannot_update_status(self):
        c = self._user_client()
        resp = c.post(reverse("update-user-status"), {
            "HRMS_ID": "200", "status": "accepted",
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_regular_user_cannot_view_document_logs(self):
        c = self._user_client()
        resp = c.get(reverse("document-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_regular_user_cannot_view_user_logs(self):
        c = self._user_client()
        resp = c.get(reverse("user-logs"))
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    def test_regular_user_cannot_view_registrations(self):
        c = self._user_client()
        resp = c.get(reverse("registration-list"))
        self.assertEqual(resp.status_code, http_status.HTTP_403_FORBIDDEN)

    # -- password never exposed ---------------------------------------------
    def test_user_list_password_not_exposed(self):
        c = self._admin_client()
        resp = c.get(reverse("registration-list"))
        for u in resp.data:
            self.assertNotIn("password", u)

    # -- registration creates pending user ----------------------------------
    def test_new_user_always_pending(self):
        """Even if payload tries to set user_status, it stays pending."""
        resp = self.client.post(reverse("register"), {
            "HRMS_ID": "HACK-STATUS",
            "password": "strongpass1",
            "user_status": "accepted",  # attempt to escalate
        }, format="json")
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        user = User.objects.get(HRMS_ID="HACK-STATUS")
        self.assertEqual(user.user_status, "pending")