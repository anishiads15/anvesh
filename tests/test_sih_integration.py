import pytest
from datetime import datetime, timedelta
from models.complaint import Complaint, ComplaintStatusHistory
from models.institution import Institution
from models.user import User
from models.overlap import OverlapRelationship
from models.notification import Notification
from models.audit import AuditEvent
from routes.reports import sanitize_csv_cell


def test_otp_login_student(client, db_session):
    """Test demo OTP login for student using identifier and fixed OTP 123456."""
    user = User(
        display_name="Priya Nair (Test)",
        username="priya_test",
        email="priya@test.edu",
        role=User.ROLE_COMPLAINANT,
        identifier="1DS22CS089_TEST",
        password_hash="dummy",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    # 1. Invalid OTP
    resp_bad = client.post("/api/auth/otp-login", json={
        "identifier": "1DS22CS089_TEST",
        "otp": "999999",
    })
    assert resp_bad.status_code == 401

    # 2. Valid demo OTP
    resp_good = client.post("/api/auth/otp-login", json={
        "identifier": "1DS22CS089_TEST",
        "otp": "123456",
    })
    assert resp_good.status_code == 200
    data = resp_good.get_json()
    assert "token" in data
    assert data["username"] == "priya_test"
    assert data["identifier"] == "1DS22CS089_TEST"


def test_auditor_read_only_access(client, db_session, sample_institution):
    """Auditor (viewer) has read access to reports and audit log, but cannot mutate records."""
    auditor = User(
        display_name="Auditor Test",
        username="auditor_test",
        email="auditor@mhrd.gov.in",
        role=User.ROLE_AUDITOR,
        is_active=True,
    )
    auditor.set_password("AuditorPass123")

    c = Complaint(
        reference_number="AICTE-2026-AUDIT-MUT",
        title="Audit Mutation Test",
        description="Testing that auditor write operations are blocked with HTTP 403.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
        created_at=datetime.utcnow(),
    )
    db_session.add_all([auditor, c])
    db_session.commit()

    # Login via web form
    client.post("/login", data={"username": "auditor_test", "password": "AuditorPass123"})

    # 1. Auditor can view dashboard and reports
    resp_dash = client.get("/dashboard")
    assert resp_dash.status_code == 200

    resp_reports = client.get("/reports")
    assert resp_reports.status_code == 200

    resp_audit = client.get("/settings/audit-log")
    assert resp_audit.status_code == 200

    # 2. Auditor attempting write action gets 403 Forbidden
    resp_write = client.post(f"/complaints/{c.id}/status", data={"status": "Resolved"})
    assert resp_write.status_code == 403


def test_fix1_registration_date_integrity(client, complainant_user, super_admin_user, sample_institution, db_session):
    """Fix 1: Original complaint registration timestamp is preserved consistently across views."""
    exact_time = datetime(2026, 10, 24, 23, 58, 45)  # Near midnight
    c = Complaint(
        reference_number="AICTE-2026-DATE-TEST",
        title="Midnight Registration Test",
        description="Testing timestamp fidelity across complainant, reviewer, and admin views.",
        institution_id=sample_institution.id,
        category="Safety and Security",
        priority="Medium",
        status="Submitted",
        complainant_user_id=complainant_user.id,
        complainant_name=complainant_user.display_name,
        created_at=exact_time,
    )
    db_session.add(c)
    db_session.commit()

    # Complainant view
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})
    resp_student = client.get(f"/student/complaints/{c.id}")
    assert resp_student.status_code == 200
    assert b"24 October 2026" in resp_student.data or b"24 Oct 2026" in resp_student.data
    client.get("/logout")

    # Admin view
    client.post("/login", data={"username": super_admin_user.username, "password": "AdminPass123"})
    resp_admin = client.get(f"/complaints/{c.id}")
    assert resp_admin.status_code == 200
    assert b"24 October 2026" in resp_admin.data or b"24 Oct 2026" in resp_admin.data


def test_fix2_action_taken_section_after_acceptance(client, institution_admin_user, sample_institution, db_session):
    """Fix 2: Reviewer records Action Taken after accepting; record persists and does NOT mark resolved."""
    c = Complaint(
        reference_number="AICTE-2026-ACTION-TEST",
        title="Water Purifier Maintenance",
        description="Water purifier filters need scheduled replacement.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        priority="Medium",
        status="Submitted",
        created_at=datetime.utcnow(),
    )
    db_session.add(c)
    db_session.commit()

    client.post("/login", data={"username": institution_admin_user.username, "password": "InstPass123"})

    # 1. Acknowledge / Accept
    client.post(f"/complaints/{c.id}/institutional-action", data={
        "action": "acknowledge",
        "official_remarks": "Maintenance team notified.",
    })
    db_session.refresh(c)
    assert c.status == "Under Institutional Review"

    # 2. Record Action Taken
    resp_act = client.post(f"/complaints/{c.id}/institutional-action", data={
        "action": "record_action",
        "action_taken_notes": "Plumber inspected water inlet and replaced cartridge filters.",
    }, follow_redirects=True)
    assert resp_act.status_code == 200

    db_session.refresh(c)
    # Status MUST NOT jump to resolved!
    assert c.status == "Under Institutional Review"
    assert "replaced cartridge filters" in c.official_remarks

    # Verify history log recorded the action taken
    sh = db_session.query(ComplaintStatusHistory).filter_by(complaint_id=c.id).order_by(ComplaintStatusHistory.id.desc()).first()
    assert sh is not None
    assert "Action Taken" in sh.notes


def test_fix3_complainant_tracking_genuine_completion(client, complainant_user, super_admin_user, sample_institution, db_session):
    """Fix 3: Complainant tracking displays genuine status, resolution statement, feedback, and reopen."""
    c = Complaint(
        reference_number="AICTE-2026-TRACK-TEST",
        title="Wi-Fi Router Failure in Block C",
        description="Router dead; no internet connectivity in computer lab.",
        institution_id=sample_institution.id,
        category="Laboratory Equipment and Infrastructure",
        priority="High",
        status="Under Investigation",
        complainant_user_id=complainant_user.id,
        complainant_name=complainant_user.display_name,
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    db_session.add(c)
    db_session.commit()

    # Complainant views in-progress complaint: NOT completed
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})
    resp_inprog = client.get(f"/student/complaints/{c.id}")
    assert resp_inprog.status_code == 200
    assert b"Under Investigation" in resp_inprog.data
    assert b"Status: Resolved" not in resp_inprog.data
    client.get("/logout")

    # AICTE admin records final resolution
    client.post("/login", data={"username": super_admin_user.username, "password": "AdminPass123"})
    client.post(f"/complaints/{c.id}/aicte-action", data={
        "action": "final_resolution",
        "public_resolution_statement": "Optical fiber line re-spliced and replacement Wi-Fi router installed.",
        "aicte_remarks": "Completed successfully.",
    })
    client.get("/logout")

    # Complainant views resolved complaint
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})
    resp_resolved = client.get(f"/student/complaints/{c.id}")
    assert resp_resolved.status_code == 200
    assert b"Status: Resolved" in resp_resolved.data
    assert b"replacement Wi-Fi router installed" in resp_resolved.data


def test_api_tamper_protection_and_role_isolation(client, db_session, sample_institution):
    """API endpoints enforce role isolation and prevent ID tampering."""
    u1 = User(display_name="Student One", username="std1", email="s1@t.com", role=User.ROLE_COMPLAINANT, identifier="ID_1", password_hash="dummy", is_active=True)
    u2 = User(display_name="Student Two", username="std2", email="s2@t.com", role=User.ROLE_COMPLAINANT, identifier="ID_2", password_hash="dummy", is_active=True)
    db_session.add_all([u1, u2])
    db_session.commit()

    c1 = Complaint(reference_number="AICTE-2026-CMP-U1", title="Case 1", description="Desc 1", institution_id=sample_institution.id, category="Other", priority="Low", status="Submitted", complainant_user_id=u1.id)
    c2 = Complaint(reference_number="AICTE-2026-CMP-U2", title="Case 2", description="Desc 2", institution_id=sample_institution.id, category="Other", priority="Low", status="Submitted", complainant_user_id=u2.id)
    db_session.add_all([c1, c2])
    db_session.commit()

    # Login as student 1 via OTP
    resp_login = client.post("/api/auth/otp-login", json={"identifier": "ID_1", "otp": "123456"})
    token1 = resp_login.get_json()["token"]

    # Student 1 can access Case 1
    resp_own = client.get(f"/api/complaints/{c1.id}", headers={"Authorization": f"Bearer {token1}"})
    assert resp_own.status_code == 200

    # Student 1 CANNOT access Case 2 (tamper protection)
    resp_tamper = client.get(f"/api/complaints/{c2.id}", headers={"Authorization": f"Bearer {token1}"})
    assert resp_tamper.status_code == 403

    # Student 1 CANNOT access overlaps list
    resp_overlaps = client.get("/api/overlaps", headers={"Authorization": f"Bearer {token1}"})
    assert resp_overlaps.status_code == 403

    # Student 1 CANNOT access central reports
    resp_reports = client.get("/api/reports", headers={"Authorization": f"Bearer {token1}"})
    assert resp_reports.status_code == 403
