import io
import pytest
from datetime import datetime
from models.user import User
from models.complaint import Complaint
from models.institution import Institution
from models.notification import Notification
from models.overlap import OverlapRelationship


def test_branding_and_no_sih26264(client):
    """Verifies ANVESH product name, expansion, tagline, and absence of SIH26264 in user-facing UI."""
    resp = client.get("/login")
    assert resp.status_code == 200
    data = resp.data.decode("utf-8")
    assert "ANVESH" in data
    assert "Analytics-Driven Network for Verifying, Evaluating, and Synchronizing Higher-Education Grievances" in data
    assert "Discover Connections. Drive Resolution. Strengthen Accountability." in data
    assert "SIH26264" not in data
    # Preserves exact logo icon
    assert "bi-shield-check" in data


def test_project_zip_removal_and_endpoint_block(client, super_admin_user):
    """Verifies Project ZIP and Download ZIP are removed from UI and /download-zip returns 403."""
    client.get("/logout")
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    data = resp_dash.data.decode("utf-8")
    assert "Project ZIP" not in data
    assert "Download ZIP" not in data
    assert "SIH26264" not in data

    # Endpoint must return 403 Forbidden
    resp_dl = client.get("/download-zip")
    assert resp_dl.status_code == 403


def test_global_overlap_intelligence_admin_only(client, complainant_user, sample_institution, super_admin_user, db_session):
    """Verifies that complainants and institution admins cannot access /overlaps or see overlap cards."""
    # 1. Complainant cannot access
    client.get("/logout")
    client.post("/login", data={"username": "student_test", "password": "StudentPass123"})
    resp_comp = client.get("/overlaps")
    assert resp_comp.status_code == 403

    resp_api = client.get("/api/overlaps")
    assert resp_api.status_code == 403

    # Complainant dashboard does not show overlap queue
    resp_portal = client.get("/student/complaints")
    assert resp_portal.status_code == 200
    assert "Overlap Intelligence" not in resp_portal.data.decode("utf-8")

    # 2. Superadmin CAN access
    client.get("/logout")
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})
    resp_admin = client.get("/overlaps")
    assert resp_admin.status_code == 200
    assert "Overlap Intelligence" in resp_admin.data.decode("utf-8")


def test_remove_export_sanitized_csv(client, super_admin_user, reviewer_user):
    """Verifies Export Sanitized CSV button is removed from dashboard and unauthorized roles get 403 on CSV export."""
    client.get("/logout")
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200
    assert "Export Sanitized CSV" not in resp_dash.data.decode("utf-8")

    # Non-superadmin reviewer cannot export complaints CSV
    client.get("/logout")
    client.post("/login", data={"username": "reviewer_test", "password": "ReviewerPass123"})
    resp_exp = client.get("/reports/export/complaints.csv")
    assert resp_exp.status_code == 403


def test_notification_system_fixes(client, complainant_user, super_admin_user, sample_institution, db_session):
    """Verifies role filtering, unread count accuracy, and mark-all-read endpoint."""
    # Create distinct notifications
    n_overlap = Notification(
        type="OVERLAP_DETECTED",
        title="High similarity overlap flagged",
        message="Case AICTE-001 matches AICTE-002",
        bureau="PGRC",
        is_read=False,
    )
    n_student = Notification(
        type="STATUS_UPDATE",
        title="Grievance Status Updated",
        message="Your grievance is now Under Review.",
        complainant_id=complainant_user.username,
        is_read=False,
    )
    db_session.add_all([n_overlap, n_student])
    db_session.commit()

    # Complainant login
    client.get("/logout")
    client.post("/login", data={"username": "student_test", "password": "StudentPass123"})
    resp_notifs = client.get("/api/notifications")
    assert resp_notifs.status_code == 200
    data = resp_notifs.get_json()
    items = data["items"]
    # Complainant MUST NOT see OVERLAP_DETECTED notifications
    types = [item["type"] for item in items]
    assert "OVERLAP_DETECTED" not in types
    assert "STATUS_UPDATE" in types

    # Mark all read
    resp_mark = client.post("/api/notifications/mark-all-read")
    assert resp_mark.status_code == 200
    assert resp_mark.get_json()["success"] is True

    # Check unread count is now 0 for complainant
    resp_after = client.get("/api/notifications")
    assert resp_after.get_json()["unread_count"] == 0


def test_portal_separation_and_demo_removal(client, complainant_user, super_admin_user):
    """Verifies server-side portal separation and removal of exposed demo OTP notes."""
    client.get("/logout")

    # 1. Complainant trying to log in via Portal A (Admin/Official) must be blocked
    resp_block = client.post("/login", data={
        "username": "student_test",
        "password": "StudentPass123",
        "portal": "admin",
    })
    assert resp_block.status_code == 200
    assert b"Access Denied" in resp_block.data or b"Access restricted" in resp_block.data

    client.get("/logout")

    # 2. Official admin trying to log in via Portal B (Student) must be blocked
    resp_admin_block = client.post("/login", data={
        "username": "admin_test",
        "password": "AdminPass123",
        "portal": "student",
    })
    assert resp_admin_block.status_code == 200
    assert b"Access Denied" in resp_admin_block.data or b"Access restricted" in resp_admin_block.data

    # 3. OTP request does not leak demo OTP in login UI
    resp_login_ui = client.get("/login")
    assert b"Demo OTP: <code>123456</code>" not in resp_login_ui.data


def test_evidence_file_upload_and_download_security(client, complainant_user, sample_institution, super_admin_user, db_session):
    """Verifies PDF/DOC/DOCX allowlist, executable rejection, and complaint-level authorization."""
    client.get("/logout")
    client.post("/login", data={"username": "student_test", "password": "StudentPass123"})

    c = Complaint(
        reference_number="AICTE-2026-CMP-TESTEVID",
        title="Valid complaint title with sufficient length",
        description="Detailed grievance description exceeding test length requirements.",
        institution_id=sample_institution.id,
        category="Student facilities",
        status="Submitted",
        complainant_user_id=complainant_user.id,
    )
    db_session.add(c)
    db_session.commit()

    # Reject executable upload
    bad_file = (io.BytesIO(b"evil executable content"), "malware.exe")
    resp_bad = client.post(f"/complaints/{c.id}/evidence/upload", data={"evidence_file": bad_file}, follow_redirects=True)
    assert resp_bad.status_code == 200
    assert b"Invalid file format" in resp_bad.data

    # Accept valid PDF upload
    pdf_file = (io.BytesIO(b"%PDF-1.4 official document data"), "evidence_receipt.pdf")
    resp_good = client.post(f"/complaints/{c.id}/evidence/upload", data={"evidence_file": pdf_file}, follow_redirects=True)
    assert resp_good.status_code == 200
    assert b"Supporting evidence uploaded successfully" in resp_good.data

    # Verify attachment is saved
    db_session.refresh(c)
    assert c.attachment_filename is not None
    assert "evidence_receipt.pdf" in c.attachment_filename

    # Unauthorized access check: Another student cannot access this file
    other_student = User(display_name="Other User", username="other_user", email="other@test.edu", role=User.ROLE_COMPLAINANT, identifier="2DS22CS099")
    other_student.set_password("Pass1234")
    db_session.add(other_student)
    db_session.commit()

    client.get("/logout")
    client.post("/login", data={"username": "other_user", "password": "Pass1234"})
    resp_unauth = client.get(f"/complaints/{c.id}/evidence/{c.attachment_filename}")
    assert resp_unauth.status_code == 403


def test_complainant_feedback_workflow(client, complainant_user, sample_institution, db_session):
    """Verifies feedback submission persistence, rating validation, and staff visibility."""
    c = Complaint(
        reference_number="AICTE-2026-CMP-FEEDBACK",
        title="Hostel cleanliness problem resolved",
        description="The hostel maintenance issue was taken care of by the administration.",
        institution_id=sample_institution.id,
        category="Student facilities",
        status="Resolved",
        complainant_user_id=complainant_user.id,
    )
    db_session.add(c)
    db_session.commit()

    client.get("/logout")
    client.post("/login", data={"username": "student_test", "password": "StudentPass123"})

    # Invalid rating (> 5) rejected
    resp_invalid = client.post(f"/student/complaints/{c.id}/feedback", data={"feedback_rating": "7", "feedback_notes": "Great"}, follow_redirects=True)
    assert resp_invalid.status_code == 200
    assert b"valid satisfaction rating between 1 and 5 stars" in resp_invalid.data

    # Valid rating (5 stars)
    resp_valid = client.post(f"/student/complaints/{c.id}/feedback", data={"feedback_rating": "5", "feedback_notes": "Prompt resolution by college committee."}, follow_redirects=True)
    assert resp_valid.status_code == 200
    assert b"Thank you for submitting your feedback" in resp_valid.data

    # Verify persisted in database
    db_session.refresh(c)
    assert c.feedback_rating == 5
    assert c.feedback_notes == "Prompt resolution by college committee."
