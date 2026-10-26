import pytest
from datetime import datetime
from models.complaint import Complaint, ComplaintStatusHistory
from models.institution import Institution
from models.user import User
from models.audit import AuditEvent


def test_three_portal_logins(client, complainant_user, institution_admin_user, super_admin_user):
    """Test that each of the three user roles logs in and redirects to their proper portal."""
    # 1. Complainant Login
    resp_student = client.post("/login", data={
        "username": complainant_user.username,
        "password": "StudentPass123"
    }, follow_redirects=False)
    assert resp_student.status_code == 302
    assert "/student/complaints" in resp_student.headers["Location"]
    client.get("/logout")

    # 2. Institutional Reviewer Login
    resp_inst = client.post("/login", data={
        "username": institution_admin_user.username,
        "password": "InstPass123"
    }, follow_redirects=False)
    assert resp_inst.status_code == 302
    assert "/dashboard" in resp_inst.headers["Location"]
    client.get("/logout")

    # 3. AICTE Officer / Super Admin Login
    resp_admin = client.post("/login", data={
        "username": super_admin_user.username,
        "password": "AdminPass123"
    }, follow_redirects=False)
    assert resp_admin.status_code == 302
    assert "/dashboard" in resp_admin.headers["Location"]
    client.get("/logout")


def test_complainant_access_restrictions(client, complainant_user, sample_institution, sample_institution_2, db_session):
    """Ensure complainants cannot access administrative dashboards, overlap queues, reports, or other users' complaints."""
    # Create another user and their complaint
    other_user = User(
        display_name="Other Student",
        username="other_student",
        email="other@college.edu",
        role=User.ROLE_COMPLAINANT,
        is_active=True,
    )
    other_user.set_password("Pass123")
    db_session.add(other_user)
    db_session.commit()

    other_complaint = Complaint(
        reference_number="AICTE-2026-CMP-OTHER",
        title="Other student grievance",
        description="Private grievance details of another student.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        priority="Medium",
        status="Open",
        complainant_user_id=other_user.id,
        complainant_name=other_user.display_name,
        created_at=datetime.utcnow(),
    )
    db_session.add(other_complaint)
    db_session.commit()

    # Log in as complainant
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})

    # Complainant accessing /dashboard should be redirected to /student/complaints
    resp_dash = client.get("/dashboard", follow_redirects=False)
    assert resp_dash.status_code == 302
    assert "/student/complaints" in resp_dash.headers["Location"]

    # Complainant accessing /overlaps should get 403 Forbidden
    resp_overlaps = client.get("/overlaps")
    assert resp_overlaps.status_code == 403

    # Complainant accessing /reports should get 403 Forbidden
    resp_reports = client.get("/reports")
    assert resp_reports.status_code == 403

    # Complainant accessing /institutions should get 403 Forbidden
    resp_insts = client.get("/institutions")
    assert resp_insts.status_code == 403

    # Complainant attempting to view other student's complaint detail should get 403 Forbidden
    resp_detail = client.get(f"/complaints/{other_complaint.id}")
    assert resp_detail.status_code == 403

    resp_sdetail = client.get(f"/student/complaints/{other_complaint.id}")
    assert resp_sdetail.status_code == 403


def test_institutional_reviewer_isolation(client, institution_admin_user, sample_institution, sample_institution_2, db_session):
    """Verify that an institutional reviewer cannot view or modify complaints belonging to another institution."""
    c_other = Complaint(
        reference_number="AICTE-2026-CMP-OTHER-INST",
        title="Other College Library Issue",
        description="Issues at institution 2 which reviewer 1 must not access.",
        institution_id=sample_institution_2.id,
        category="Library and Learning Resources",
        priority="Low",
        status="Open",
        created_at=datetime.utcnow(),
    )
    db_session.add(c_other)
    db_session.commit()

    # Log in as institutional reviewer for institution 1
    client.post("/login", data={"username": institution_admin_user.username, "password": "InstPass123"})

    # Accessing other institution's complaint must return 403
    resp = client.get(f"/complaints/{c_other.id}")
    assert resp.status_code == 403

    # Attempting status update on other institution's complaint must return 403
    resp_post = client.post(f"/complaints/{c_other.id}/status", data={"status": "Resolved"})
    assert resp_post.status_code == 403

    # GET /complaints/new for institutional reviewer should be prevented
    resp_new = client.get("/complaints/new", follow_redirects=False)
    assert resp_new.status_code == 302


def test_full_complaint_lifecycle_workflow(client, complainant_user, institution_admin_user, super_admin_user, sample_institution, db_session):
    """
    Test the complete 5-stage complaint lifecycle:
    1. Complainant submits complaint -> 'Submitted'
    2. Institutional reviewer reviews & acknowledges -> 'Under Institutional Review'
    3. Institutional reviewer escalates to AICTE -> 'Escalated to AICTE'
    4. AICTE officer orders formal investigation -> 'Under Investigation'
    5. AICTE officer records final resolution -> 'Resolved'
    6. Complainant views resolution, submits feedback, and requests reopen -> 'Reopened'
    """
    # 1. Complainant submits complaint
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})
    resp_create = client.post("/complaints/new", data={
        "title": "Severe shortage of lab chemicals and safety goggles",
        "description": "Chemistry practical sessions canceled due to complete absence of laboratory reagents and safety gear.",
        "institution_id": sample_institution.id,
        "category": "Laboratory Equipment and Infrastructure",
        "priority": "High",
        "attachment_filename": "chem_lab_deficiencies.pdf",
    }, follow_redirects=True)
    assert resp_create.status_code == 200

    complaint = db_session.query(Complaint).filter_by(title="Severe shortage of lab chemicals and safety goggles").first()
    assert complaint is not None
    assert complaint.complainant_user_id == complainant_user.id
    assert complaint.status == "Submitted"
    assert complaint.attachment_filename == "chem_lab_deficiencies.pdf"
    client.get("/logout")

    # 2. Institutional reviewer acknowledges complaint
    client.post("/login", data={"username": institution_admin_user.username, "password": "InstPass123"})
    resp_ack = client.post(f"/complaints/{complaint.id}/institutional-action", data={
        "action": "acknowledge",
        "official_remarks": "Chemistry department head summoned for inventory check.",
    }, follow_redirects=True)
    assert resp_ack.status_code == 200

    db_session.refresh(complaint)
    assert complaint.status == "Under Institutional Review"
    assert "inventory check" in complaint.official_remarks

    # 3. Institutional reviewer escalates to AICTE (e.g. fund deficit)
    resp_esc = client.post(f"/complaints/{complaint.id}/institutional-action", data={
        "action": "escalate",
        "escalation_reason": "Institution capital equipment grant stalled; central AICTE grant allocation required.",
        "official_remarks": "Escalated after department emergency committee meeting.",
    }, follow_redirects=True)
    assert resp_esc.status_code == 200

    db_session.refresh(complaint)
    assert complaint.status == "Escalated to AICTE"
    assert complaint.escalated_at is not None
    assert "grant stalled" in complaint.escalation_reason
    client.get("/logout")

    # 4. AICTE officer reviews escalated complaint and orders investigation
    client.post("/login", data={"username": super_admin_user.username, "password": "AdminPass123"})
    resp_inv = client.post(f"/complaints/{complaint.id}/aicte-action", data={
        "action": "investigate",
        "aicte_remarks": "Western regional office tasked to verify laboratory equipment and consumables purchase ledger.",
    }, follow_redirects=True)
    assert resp_inv.status_code == 200

    db_session.refresh(complaint)
    assert complaint.status == "Under Investigation"
    assert "Western regional office" in complaint.aicte_remarks

    # 5. AICTE officer records final statutory resolution
    resp_res = client.post(f"/complaints/{complaint.id}/aicte-action", data={
        "action": "final_resolution",
        "public_resolution_statement": "AICTE Regional Inspection team verified emergency delivery of required chemistry reagents and 60 sets of safety gear.",
        "aicte_remarks": "Closed following compliance report submission by college principal.",
    }, follow_redirects=True)
    assert resp_res.status_code == 200

    db_session.refresh(complaint)
    assert complaint.status == "Resolved"
    assert complaint.resolution_date is not None
    assert "verified emergency delivery" in complaint.public_resolution_statement
    client.get("/logout")

    # 6. Complainant views resolution, rates satisfaction, and tests reopening
    client.post("/login", data={"username": complainant_user.username, "password": "StudentPass123"})
    resp_track = client.get(f"/student/complaints/{complaint.id}")
    assert resp_track.status_code == 200
    assert b"verified emergency delivery" in resp_track.data

    # Submit feedback rating
    resp_fb = client.post(f"/student/complaints/{complaint.id}/feedback", data={
        "feedback_rating": "4",
        "feedback_notes": "Chemicals supplied, thanking AICTE for quick intervention.",
    }, follow_redirects=True)
    assert resp_fb.status_code == 200
    db_session.refresh(complaint)
    assert complaint.feedback_rating == 4

    # Request reopening if recurring
    resp_reopen = client.post(f"/student/complaints/{complaint.id}/reopen", data={
        "reopen_reason": "Glassware still insufficient for batch B experiments.",
    }, follow_redirects=True)
    assert resp_reopen.status_code == 200
    db_session.refresh(complaint)
    assert complaint.status == "Reopened"
    assert "Glassware still insufficient" in complaint.reopen_reason
