import pytest
from datetime import datetime
from models.complaint import Complaint, ComplaintStatusHistory
from models.group import RelatedComplaintGroup
from models.institution import Institution
from models.user import User
from models.audit import AuditEvent
from services.routing_service import (
    suggest_department_routing,
    DEST_PGRC,
    DEST_RC,
    DEST_INSTITUTIONAL,
    DEST_MANUAL,
)


def test_ai_department_routing_logic():
    """Verify rule-based and contextual suggestion for all 4 routing destinations."""
    # 1. PGRC (Public Grievance Redressal Committee): harassment, ragging, fees, scholarships
    pgrc_res = suggest_department_routing(
        title="Hostel ragging by senior students",
        description="First year students are facing continuous verbal abuse and ragging in hostel block B.",
        category="Ragging and Student Harassment",
    )
    assert pgrc_res["suggested_destination"] == DEST_PGRC
    assert pgrc_res["requires_human_review"] is True
    assert pgrc_res["confidence_score"] >= 0.8

    # 2. RC (Regional Committee): regulatory approval, unapproved courses, land/building norm violations
    rc_res = suggest_department_routing(
        title="Unapproved intake in AI course without AICTE permission",
        description="College admitted 120 students in AI course despite approval letter granting only 60 seats.",
        category="Academic and Examination Issues",
    )
    assert rc_res["suggested_destination"] == DEST_RC
    assert rc_res["confidence_score"] >= 0.75

    # 3. Institutional Reviewer: campus maintenance, broken laboratory equipment, drinking water
    inst_res = suggest_department_routing(
        title="Physics laboratory oscilloscope not functioning",
        description="The digital storage oscilloscopes in Physics Lab 2 have been dead for three weeks.",
        category="Laboratory Equipment and Infrastructure",
    )
    assert inst_res["suggested_destination"] == DEST_INSTITUTIONAL

    # 4. Manual Review: ambiguous or low confidence
    man_res = suggest_department_routing(
        title="Miscellaneous matter",
        description="General miscellaneous query without specific departmental keywords.",
        category="Other",
    )
    assert man_res["suggested_destination"] == DEST_MANUAL


def test_complaint_creation_populates_ai_routing(client, complainant_user, sample_institution, db_session):
    """Ensure submitting a new complaint calculates AI routing recommendation and sets initial fields."""
    client.post("/login", data={
        "username": complainant_user.username,
        "password": "StudentPass123"
    })

    resp = client.post("/complaints/new", data={
        "title": "Severe ragging by senior students in campus hostel",
        "description": "First year juniors are being subjected to severe ragging and harassment every night in Hostel Block A.",
        "institution_id": sample_institution.id,
        "category": "Ragging and Student Harassment",
        "priority": "Critical",
    }, follow_redirects=True)
    assert resp.status_code == 200

    created = db_session.query(Complaint).filter_by(institution_id=sample_institution.id).first()
    assert created is not None
    assert created.suggested_destination == DEST_PGRC
    assert created.routing_reason is not None
    assert created.routing_confidence is not None
    assert created.routing_requires_human_review is True
    assert created.routed_destination is None
    assert created.resolution_status == "Not Yet Resolved"


def test_human_routing_confirmation_and_override(client, institution_admin_user, sample_institution, db_session):
    """Institutional Reviewer can confirm AI routing or override with a required reason."""
    complaint = Complaint(
        reference_number="AICTE-2026-CMP-ROUTE1",
        title="Damaged water cooler in block 2",
        description="Drinking water cooler has broken tap and foul odor.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        priority="Medium",
        status="Submitted",
        suggested_destination=DEST_INSTITUTIONAL,
        routing_reason="Local campus maintenance matter.",
        routing_confidence=0.85,
        routing_requires_human_review=True,
    )
    db_session.add(complaint)
    db_session.commit()

    # Login as institutional reviewer
    client.post("/login", data={
        "username": institution_admin_user.username,
        "password": "InstPass123"
    })

    # 1. Accept AI Suggestion
    resp_accept = client.post(f"/complaints/{complaint.id}/route-decision", data={
        "action": "accept"
    }, follow_redirects=True)
    assert resp_accept.status_code == 200

    db_session.refresh(complaint)
    assert complaint.routed_destination == DEST_INSTITUTIONAL
    assert complaint.routing_decision == "Accepted AI Suggestion"
    assert complaint.routed_by_user_id == institution_admin_user.id
    assert complaint.routed_at is not None
    assert complaint.status == "Under Institutional Review"

    # 2. Override without reason should fail
    resp_fail_override = client.post(f"/complaints/{complaint.id}/route-decision", data={
        "action": "override",
        "destination": DEST_PGRC,
        "reason": "",
    }, follow_redirects=True)
    assert b"A required justification must be provided" in resp_fail_override.data

    # 3. Override with valid reason succeeds
    resp_ok_override = client.post(f"/complaints/{complaint.id}/route-decision", data={
        "action": "override",
        "destination": DEST_PGRC,
        "reason": "Escalated to PGRC because administration refused local sanitation repairs for 6 months.",
    }, follow_redirects=True)
    assert resp_ok_override.status_code == 200

    db_session.refresh(complaint)
    assert complaint.routed_destination == DEST_PGRC
    assert complaint.routing_decision == "Reviewer Override"
    assert "refused local sanitation repairs" in complaint.routing_override_reason


def test_shared_related_complaint_group_integrity(client, institution_admin_user, sample_institution, db_session):
    """
    Test Section 3 requirement: Link multiple complaints to a shared RelatedComplaintGroup.
    Must NOT merge or delete individual complaint records.
    Each complaint keeps distinct ID, date, complainant, and evidence.
    """
    # Create two complaints describing the same underlying lab issue
    c1 = Complaint(
        reference_number="AICTE-2026-CMP-G1",
        title="Microprocessor kits burned out",
        description="In microprocessor lab, kits 1 to 5 have blown capacitors.",
        institution_id=sample_institution.id,
        category="Laboratory Equipment and Infrastructure",
        priority="High",
        status="Open",
        complainant_name="Student One",
    )
    c2 = Complaint(
        reference_number="AICTE-2026-CMP-G2",
        title="Cannot conduct 8085 lab practicals",
        description="All kits in the hardware lab are malfunctioning due to short circuit.",
        institution_id=sample_institution.id,
        category="Laboratory Equipment and Infrastructure",
        priority="High",
        status="Open",
        complainant_name="Student Two",
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    c1_id = c1.id
    c2_id = c2.id
    c1_date = c1.created_at
    c2_date = c2.created_at

    client.post("/login", data={
        "username": institution_admin_user.username,
        "password": "InstPass123"
    })

    # Create and link group
    resp_create_grp = client.post(f"/complaints/{c1.id}/group-action", data={
        "action": "create_and_link",
        "group_title": "Microprocessor Lab Power Surge Damage",
        "root_cause": "Voltage spike on 440V line burned out all 8085 trainer kits.",
        "group_description": "Damage to hardware laboratory training boards.",
        "linked_complaint_ids": [c2.id],
    }, follow_redirects=True)
    assert resp_create_grp.status_code == 200

    db_session.refresh(c1)
    db_session.refresh(c2)

    # Verify separate complaints exist with intact IDs and metadata
    assert c1.id == c1_id
    assert c2.id == c2_id
    assert c1.reference_number == "AICTE-2026-CMP-G1"
    assert c2.reference_number == "AICTE-2026-CMP-G2"
    assert c1.complainant_name == "Student One"
    assert c2.complainant_name == "Student Two"
    assert c1.created_at == c1_date
    assert c2.created_at == c2_date

    # Verify both share the same group
    assert c1.related_group_id is not None
    assert c1.related_group_id == c2.related_group_id
    group = c1.related_group
    assert "AICTE-GRP-" in group.group_reference
    assert group.title == "Microprocessor Lab Power Surge Damage"
    assert "Voltage spike" in group.root_cause
    assert len(group.complaints) == 2


def test_group_resolution_propagation_with_explicit_selection(client, institution_admin_user, sample_institution, db_session):
    """
    Test Section 4: Solved / Not Solved / Partially Resolved / Reopened control panel.
    Reviewer marks Solved and explicitly selects which complaints in the group are genuinely addressed.
    Unselected complaints remain Open.
    """
    group = RelatedComplaintGroup(
        group_reference="AICTE-GRP-TEST-01",
        title="Hostel Water Pump Failure",
        root_cause="Submersible pump motor burned out.",
        category="Sanitation and Drinking Water",
        institution_id=sample_institution.id,
        status="Open",
    )
    db_session.add(group)
    db_session.flush()

    c1 = Complaint(
        reference_number="AICTE-2026-CMP-P1",
        title="Hostel Block A water outage",
        description="No water supply in Block A 3rd floor.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        status="Under Review",
        related_group_id=group.id,
    )
    c2 = Complaint(
        reference_number="AICTE-2026-CMP-P2",
        title="Hostel Block B water outage",
        description="Block B has dry taps.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        status="Under Review",
        related_group_id=group.id,
    )
    c3 = Complaint(
        reference_number="AICTE-2026-CMP-P3",
        title="Mess kitchen water contamination",
        description="Kitchen tap water is muddy and foul smelling.",
        institution_id=sample_institution.id,
        category="Sanitation and Drinking Water",
        status="Under Review",
        related_group_id=group.id,
    )
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    client.post("/login", data={
        "username": institution_admin_user.username,
        "password": "InstPass123"
    })

    # Reviewer marks c1 as Resolved, and propagates ONLY to c2 (pump replaced), NOT c3 (mess water still needs testing)
    resp_resolve = client.post(f"/complaints/{c1.id}/resolution-decision", data={
        "resolution_state": "Resolved",
        "public_resolution_statement": "Submersible pump motor replaced and pipeline sanitized. Normal water pressure restored.",
        "resolution_notes": "Contractor invoice #4092 completed repair.",
        "apply_to_group": "1",
        "selected_group_complaint_ids": [c2.id],  # ONLY c2 confirmed, c3 excluded!
    }, follow_redirects=True)
    assert resp_resolve.status_code == 200

    db_session.refresh(c1)
    db_session.refresh(c2)
    db_session.refresh(c3)

    # c1 is resolved
    assert c1.status == "Resolved"
    assert c1.resolution_status == "Resolved"
    assert "Normal water pressure restored" in c1.public_resolution_statement

    # c2 is resolved via confirmed propagation
    assert c2.status == "Resolved"
    assert c2.resolution_status == "Resolved"
    assert "Normal water pressure restored" in c2.public_resolution_statement

    # c3 was NOT confirmed, so it must remain Under Review!
    assert c3.status == "Under Review"
    assert c3.resolution_status == "Not Yet Resolved"
    assert c3.public_resolution_statement is None


def test_department_review_queues_endpoint(client, reviewer_user, sample_institution, db_session):
    """Ensure all review queues (PGRC, RC, Institutional, Manual, Unrouted) return 200 with proper counts."""
    # Seed one complaint for each queue
    c_pgrc = Complaint(
        reference_number="AICTE-2026-CMP-QPGRC",
        title="Harassment grievance",
        description="Harassment complaint filed by student.",
        institution_id=sample_institution.id,
        category="Ragging and Student Harassment",
        priority="High",
        status="Open",
        routed_destination=DEST_PGRC,
    )
    c_rc = Complaint(
        reference_number="AICTE-2026-CMP-QRC",
        title="Unapproved intake violation",
        description="College increased seats without approval handbook compliance.",
        institution_id=sample_institution.id,
        category="Academic and Examination Issues",
        priority="Critical",
        status="Open",
        routed_destination=DEST_RC,
    )
    c_inst = Complaint(
        reference_number="AICTE-2026-CMP-QINST",
        title="Library AC malfunctioning",
        description="Air conditioning units in central library are broken.",
        institution_id=sample_institution.id,
        category="Library and Learning Resources",
        priority="Low",
        status="Open",
        routed_destination=DEST_INSTITUTIONAL,
    )
    c_unrouted = Complaint(
        reference_number="AICTE-2026-CMP-QUNR",
        title="Awaiting triage routing",
        description="Newly registered complaint needing reviewer routing.",
        institution_id=sample_institution.id,
        category="Other",
        priority="Medium",
        status="Submitted",
        suggested_destination=DEST_MANUAL,
        routed_destination=None,
    )
    db_session.add_all([c_pgrc, c_rc, c_inst, c_unrouted])
    db_session.commit()

    client.post("/login", data={
        "username": reviewer_user.username,
        "password": "ReviewerPass123"
    })

    # 1. Main Queues page
    resp_all = client.get("/queues")
    assert resp_all.status_code == 200
    assert b"Department Review Queues" in resp_all.data
    assert b"AICTE-2026-CMP-QPGRC" in resp_all.data

    # 2. PGRC Queue
    resp_pgrc = client.get("/queues/pgrc")
    assert resp_pgrc.status_code == 200
    assert b"AICTE-2026-CMP-QPGRC" in resp_pgrc.data
    assert b"AICTE-2026-CMP-QRC" not in resp_pgrc.data

    # 3. RC Queue
    resp_rc = client.get("/queues/rc")
    assert resp_rc.status_code == 200
    assert b"AICTE-2026-CMP-QRC" in resp_rc.data
    assert b"AICTE-2026-CMP-QPGRC" not in resp_rc.data

    # 4. Institutional Queue
    resp_inst = client.get("/queues/institutional")
    assert resp_inst.status_code == 200
    assert b"AICTE-2026-CMP-QINST" in resp_inst.data

    # 5. Unrouted Queue
    resp_unrouted = client.get("/queues/unrouted")
    assert resp_unrouted.status_code == 200
    assert b"AICTE-2026-CMP-QUNR" in resp_unrouted.data


def test_student_portal_6_stage_lifecycle_and_privacy(client, complainant_user, sample_institution, db_session):
    """Complainant view shows 6-stage lifecycle and shared issue docket without leaking other students' info."""
    # Shared group with 2 complaints from 2 different students
    group = RelatedComplaintGroup(
        group_reference="AICTE-GRP-2026-PRIV",
        title="Chemistry Lab Gas Leakage",
        root_cause="Faulty main valve on LPG manifold.",
        category="Safety and Security",
        institution_id=sample_institution.id,
        status="Under Review",
    )
    db_session.add(group)
    db_session.flush()

    my_complaint = Complaint(
        reference_number="AICTE-2026-CMP-MY1",
        title="Gas smell in chemistry lab",
        description="Strong gas odor near burner stations 1-6.",
        institution_id=sample_institution.id,
        category="Safety and Security",
        status="Under Institutional Review",
        complainant_user_id=complainant_user.id,
        complainant_name="Rahul Verma (Student)",
        related_group_id=group.id,
        suggested_destination=DEST_INSTITUTIONAL,
        routed_destination=DEST_INSTITUTIONAL,
    )

    other_student_complaint = Complaint(
        reference_number="AICTE-2026-CMP-SECRET",
        title="Chemistry gas burner leak",
        description="Secret personal details of another student.",
        institution_id=sample_institution.id,
        category="Safety and Security",
        status="Under Institutional Review",
        complainant_name="Sita Gupta (Secret Student)",
        is_confidential=True,
        related_group_id=group.id,
    )
    db_session.add_all([my_complaint, other_student_complaint])
    db_session.commit()

    client.post("/login", data={
        "username": complainant_user.username,
        "password": "StudentPass123"
    })

    resp = client.get(f"/student/complaints/{my_complaint.id}")
    assert resp.status_code == 200

    # Stepper and routing info visible
    assert b"6-Stage Lifecycle Resolution Pathway" in resp.data
    assert b"Institutional Review" in resp.data
    assert b"AICTE-GRP-2026-PRIV" in resp.data
    assert b"Chemistry Lab Gas Leakage" in resp.data

    # Privacy guarantee: other student's name and private description MUST NOT be exposed!
    assert b"Sita Gupta" not in resp.data
    assert b"Secret personal details" not in resp.data
