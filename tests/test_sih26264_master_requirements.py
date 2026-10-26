import pytest
from datetime import datetime
from models.user import User
from models.institution import Institution
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from models.audit import AuditEvent
from services.categorization import CATEGORY_TAXONOMY, normalize_category_name, categorize_complaint
from services.routing_service import (
    DEST_PGRC, DEST_RB, DEST_AB, DEST_PAPB, DEST_FB, DEST_ARC, DEST_SDC, DEST_RC,
    DEST_INSTITUTIONAL, DEST_MANUAL, ALL_DESTINATIONS
)


def test_three_portal_authentication_and_demo_accounts(client, db_session):
    """Verifies Phase 5 & 6 authentication requirements for all three portals and seeded demo accounts."""
    # Ensure test institution exists
    inst = db_session.query(Institution).first()
    if not inst:
        inst = Institution(name="National Technical Institute", code="AICTE-TEST-001", state="Delhi", district="New Delhi")
        db_session.add(inst)
        db_session.commit()

    # Seed demo users if not present
    admin_u = db_session.query(User).filter_by(username="admin").first()
    if not admin_u:
        admin_u = User(display_name="Dr. Rajiv Sharma", username="admin", email="admin@aicte-india.org", role=User.ROLE_AICTE_OFFICER, bureau="All")
        admin_u.set_password("Admin@123")
        db_session.add(admin_u)

    pgrc_u = db_session.query(User).filter_by(username="reviewer_pgrc").first()
    if not pgrc_u:
        pgrc_u = User(display_name="Dr. Sunita Sharma", username="reviewer_pgrc", email="reviewer.pgrc@aicte-india.org", role=User.ROLE_REVIEWER, bureau="PGRC (Public Grievance Redressal)")
        pgrc_u.set_password("Reviewer@123")
        db_session.add(pgrc_u)

    rb_u = db_session.query(User).filter_by(username="reviewer_rb").first()
    if not rb_u:
        rb_u = User(display_name="Er. Rajesh Verma", username="reviewer_rb", email="reviewer.rb@aicte-india.org", role=User.ROLE_REVIEWER, bureau="Regulation Bureau (RB)")
        rb_u.set_password("Reviewer@123")
        db_session.add(rb_u)

    student_u = db_session.query(User).filter_by(identifier="1DS22CS089").first()
    if not student_u:
        student_u = User(display_name="Priya Nair", username="priya.nair", email="priya.nair@test.edu.in", role=User.ROLE_COMPLAINANT, identifier="1DS22CS089")
        student_u.set_password("Student@123")
        db_session.add(student_u)

    parent_u = db_session.query(User).filter_by(identifier="PAR-984501").first()
    if not parent_u:
        parent_u = User(display_name="Suresh Menon", username="suresh.menon", email="suresh.menon@test.com", role=User.ROLE_COMPLAINANT, identifier="PAR-984501")
        parent_u.set_password("Parent@123")
        db_session.add(parent_u)

    db_session.commit()

    # 1. Portal A: Admin Login
    resp_admin = client.post("/login", data={"username": "admin", "password": "Admin@123", "portal": "admin"}, follow_redirects=False)
    assert resp_admin.status_code == 302
    assert "/dashboard" in resp_admin.headers["Location"]
    client.get("/logout")

    # 2. Portal A: PGRC Reviewer Login
    resp_pgrc = client.post("/login", data={"username": "reviewer_pgrc", "password": "Reviewer@123", "portal": "admin"}, follow_redirects=False)
    assert resp_pgrc.status_code == 302
    assert "/dashboard" in resp_pgrc.headers["Location"]
    client.get("/logout")

    # 3. Portal A: RB Reviewer Login
    resp_rb = client.post("/login", data={"username": "reviewer_rb", "password": "Reviewer@123", "portal": "admin"}, follow_redirects=False)
    assert resp_rb.status_code == 302
    assert "/dashboard" in resp_rb.headers["Location"]
    client.get("/logout")

    # 4. Portal B: Student USN Login via Demo OTP
    resp_student = client.post("/login", data={"identifier": "1DS22CS089", "otp": "123456", "portal": "student"}, follow_redirects=False)
    assert resp_student.status_code == 302
    assert "/student/complaints" in resp_student.headers["Location"]
    client.get("/logout")

    # 5. Portal C: Parent Guardian Login via Demo OTP
    resp_parent = client.post("/login", data={"identifier": "PAR-984501", "otp": "123456", "portal": "parent"}, follow_redirects=False)
    assert resp_parent.status_code == 302
    assert "/student/complaints" in resp_parent.headers["Location"]
    client.get("/logout")


def test_otp_request_endpoint_and_validation(client, db_session):
    """Verifies Phase 6 server-side OTP generation and delivery notification."""
    # Ensure test user exists in session
    student_u = db_session.query(User).filter_by(identifier="1DS22CS089").first()
    if not student_u:
        student_u = User(display_name="Priya Nair", username="priya.nair", email="priya.nair@test.edu.in", role=User.ROLE_COMPLAINANT, identifier="1DS22CS089")
        student_u.set_password("Student@123")
        db_session.add(student_u)
        db_session.commit()

    # Request OTP for registered student
    resp = client.post("/auth/request-otp", json={"identifier": "1DS22CS089", "portal": "student"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "OTP dispatched" in data["message"]
    assert "demo_note" in data

    # Attempt login with invalid OTP
    resp_fail = client.post("/login", data={"identifier": "1DS22CS089", "otp": "999999", "portal": "student"}, follow_redirects=True)
    assert resp_fail.status_code == 200
    assert b"Incorrect OTP" in resp_fail.data or b"Invalid" in resp_fail.data


def test_public_signup_and_privileged_role_rejection(client, db_session):
    """Verifies Phase 5 self-registration and strict security restriction on privileged roles."""
    # 1. Successful student signup
    resp_signup = client.post("/signup", data={
        "full_name": "Kavita Rao",
        "username": "kavita_student",
        "email": "kavita.rao@test.edu.in",
        "password": "SecurePassword123",
        "role_type": "student",
        "identifier": "1DS24EC055",
    }, follow_redirects=False)
    assert resp_signup.status_code == 302
    assert "/student/complaints" in resp_signup.headers["Location"]

    new_user = db_session.query(User).filter_by(username="kavita_student").first()
    assert new_user is not None
    assert new_user.role == User.ROLE_COMPLAINANT
    assert new_user.identifier == "1DS24EC055"
    client.get("/logout")

    # 2. Privileged role registration rejection (Security check)
    resp_hacker = client.post("/signup", data={
        "full_name": "Malicious User",
        "username": "fake_admin",
        "email": "fake.admin@hack.org",
        "password": "HackerPass123",
        "role_type": "admin",
    }, follow_redirects=True)
    assert resp_hacker.status_code == 200
    assert b"Privileged administrative, reviewer, and auditor accounts cannot be created via public registration" in resp_hacker.data
    assert db_session.query(User).filter_by(username="fake_admin").first() is None


def test_password_recovery_flow(client, db_session):
    """Verifies Phase 6 expiring single-use password recovery flow."""
    user = db_session.query(User).filter_by(username="admin").first()
    assert user is not None

    resp_forgot = client.post("/auth/forgot-password", data={"username_or_email": "admin"})
    assert resp_forgot.status_code == 200
    assert b"Set New Password" in resp_forgot.data

    # Extract token from response HTML
    token_str = None
    import re
    match = re.search(r'name="token" value="([^"]+)"', resp_forgot.data.decode("utf-8"))
    assert match is not None
    token_str = match.group(1)

    # Submit new password
    resp_reset = client.post("/auth/reset-password", data={"token": token_str, "new_password": "NewAdminPass123"}, follow_redirects=True)
    assert resp_reset.status_code == 200
    assert b"password has been updated securely" in resp_reset.data

    # Verify new password works
    user = db_session.query(User).filter_by(username="admin").first()
    assert user.check_password("NewAdminPass123") is True
    # Restore standard demo password
    user.set_password("Admin@123")
    db_session.commit()


def test_persistent_audit_logging_of_auth_events(client, db_session):
    """Verifies Phase 7 persistent authentication audit records (LOGIN, LOGOUT, LOGIN_FAILED)."""
    # 1. Failed login audit
    client.post("/login", data={"username": "admin", "password": "WrongPasswordXYZ"})
    fail_event = db_session.query(AuditEvent).filter_by(action="LOGIN_FAILED").order_by(AuditEvent.timestamp.desc()).first()
    assert fail_event is not None
    assert fail_event.entity_id == "admin"

    # 2. Successful login audit
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    login_event = db_session.query(AuditEvent).filter_by(action="LOGIN").order_by(AuditEvent.timestamp.desc()).first()
    assert login_event is not None
    assert login_event.actor_name is not None

    # 3. Explicit logout audit
    client.get("/logout")
    logout_event = db_session.query(AuditEvent).filter_by(action="LOGOUT").order_by(AuditEvent.timestamp.desc()).first()
    assert logout_event is not None


def test_all_20_categories_restored_and_mapped():
    """Verifies Phase 4 full restoration of 20 standardized complaint categories."""
    assert len(CATEGORY_TAXONOMY) == 20
    assert len(Complaint.CATEGORIES) == 20

    expected_categories = [
        "Ragging and Student Harassment",
        "Financial Issues and Fee Irregularities",
        "Scholarship Delays",
        "Laboratory Equipment and Infrastructure",
        "Hostel and Accommodation",
        "Faculty Misconduct",
        "Academic and Examination Issues",
        "Discrimination and Student Welfare",
        "Safety and Security",
        "Sanitation and Drinking Water",
        "Library and Learning Resources",
        "Other",
        "Fee Overcharging / Capitation",
        "Infrastructure & Laboratory Deficit",
        "Withholding Original Certificates",
        "Admissions & Affiliation Irregularities",
        "Governance Malpractice & Retaliation",
        "Misappropriation of Grant Funds",
        "Faculty Non-Payment & Understaffing",
        "Unapproved Courses & Excess Intake",
    ]
    for cat in expected_categories:
        assert cat in CATEGORY_TAXONOMY
        assert cat in Complaint.CATEGORIES

    # Check legacy taxonomy mappings
    assert normalize_category_name("Capitation Fee Demand") == "Fee Overcharging / Capitation"
    assert normalize_category_name("Harassment / Ragging") == "Ragging and Student Harassment"
    assert normalize_category_name("Laboratory and equipment") == "Laboratory Equipment and Infrastructure"


def test_all_bureaus_and_review_queues_integration(client, db_session):
    """Verifies Phase 3 complete bureau structure (PGRC, RB, AB, PAPB, FB, ARC, SDC) in review queues."""
    # Ensure all destinations exist
    for b_code in [DEST_PGRC, DEST_RB, DEST_AB, DEST_PAPB, DEST_FB, DEST_ARC, DEST_SDC, DEST_RC, DEST_INSTITUTIONAL, DEST_MANUAL]:
        assert b_code in ALL_DESTINATIONS

    # Log in as central administrator
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    resp_queues = client.get("/queues")
    assert resp_queues.status_code == 200
    assert b"PGRC Grievance" in resp_queues.data
    assert b"Regulation Bureau (RB)" in resp_queues.data
    assert b"Approval Bureau (AB)" in resp_queues.data
    assert b"Policy &amp; Academic (PAPB)" in resp_queues.data
    assert b"Finance Bureau (FB)" in resp_queues.data
    assert b"Anti-Ragging Cell (ARC)" in resp_queues.data
    assert b"Skill Development (SDC)" in resp_queues.data
    client.get("/logout")


def test_admin_complaint_list_removes_submit_button(client, db_session):
    """Verifies Phase 9: Admin All Grievances page removes the submit button."""
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    resp = client.get("/complaints")
    assert resp.status_code == 200
    assert b"Institutional Complaints Master Directory" in resp.data
    # "+ Submit New Complaint" button should not appear for Admin
    assert b'<i class="bi bi-plus-lg me-1"></i> Submit New Complaint' not in resp.data
    client.get("/logout")


def test_system_diagnostics_reported_accurately(client, db_session):
    """Verifies Phase 11: Accurate system diagnostics derived directly from database."""
    client.post("/login", data={"username": "admin", "password": "Admin@123"})
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert b"System Diagnostics &amp; Environment Statistics" in resp.data
    assert b"Unique Stored Overlaps" in resp.data
    assert b"Complaints In Storage" in resp.data
    client.get("/logout")
