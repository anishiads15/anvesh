import pytest
from models.complaint import Complaint, ComplaintStatusHistory
from models.audit import AuditEvent


def test_complaint_creation_and_reference(client, super_admin_user, sample_institution, db_session):
    """Test complaint creation with server-side validation and sequential reference generation."""
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})

    response = client.post("/complaints/new", data={
        "title": "Computer lab hardware failure",
        "description": "All desktop monitors and testing kits in the computing laboratory have stopped working.",
        "institution_id": sample_institution.id,
        "source_channel": "Student grievance",
        "category": "Laboratory and equipment",
        "priority": "High",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"successfully registered" in response.data

    complaint = db_session.query(Complaint).filter_by(title="Computer lab hardware failure").first()
    assert complaint is not None
    assert complaint.reference_number.startswith("AICTE-")
    assert complaint.category == "Laboratory and equipment"
    assert complaint.status == "Open"

    # Status history record created
    history = db_session.query(ComplaintStatusHistory).filter_by(complaint_id=complaint.id).first()
    assert history is not None
    assert history.new_status == "Open"

    # Audit event created
    audit = db_session.query(AuditEvent).filter_by(action="COMPLAINT_CREATED").first()
    assert audit is not None
    assert audit.entity_id == complaint.reference_number


def test_complaint_validation_error(client, super_admin_user, sample_institution):
    """Test validation errors for short title or description."""
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})

    response = client.post("/complaints/new", data={
        "title": "Bad",  # Too short (< 5 chars)
        "description": "Short",  # Too short (< 15 chars)
        "institution_id": sample_institution.id,
    }, follow_redirects=True)

    assert b"at least 5 characters" in response.data
    assert b"at least 15 characters" in response.data


def test_complaint_status_update(client, reviewer_user, sample_institution, db_session):
    """Test status update creates lifecycle history and resolution timestamps."""
    client.post("/login", data={"username": "reviewer_test", "password": "ReviewerPass123"})

    c = Complaint(
        reference_number="AICTE-2026-CMP-TEST1",
        title="Testing complaint for status",
        description="Detailed description for status update test case verification.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
    )
    db_session.add(c)
    db_session.commit()

    response = client.post(f"/complaints/{c.id}/status", data={
        "status": "Resolved",
        "notes": "Contractor repaired water pump facility."
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"successfully updated" in response.data
    assert b"Resolved" in response.data

    updated_c = db_session.query(Complaint).get(c.id)
    assert updated_c.status == "Resolved"
    assert updated_c.resolution_date is not None
    assert updated_c.resolution_notes == "Contractor repaired water pump facility."

    history = db_session.query(ComplaintStatusHistory).filter_by(complaint_id=c.id, new_status="Resolved").first()
    assert history is not None


def test_institutional_admin_isolation(client, institution_admin_user, sample_institution_2, db_session):
    """Test institutional administrator cannot access another institution's complaint."""
    client.post("/login", data={"username": "inst_admin_test", "password": "InstPass123"})

    # Complaint belongs to institution 2, whereas inst_admin belongs to institution 1
    foreign_complaint = Complaint(
        reference_number="AICTE-2026-CMP-FOR1",
        title="Foreign institution complaint",
        description="Complaint filed for a different institution campus.",
        institution_id=sample_institution_2.id,
        category="Academic quality",
        status="Open",
    )
    db_session.add(foreign_complaint)
    db_session.commit()

    response = client.get(f"/complaints/{foreign_complaint.id}")
    assert response.status_code == 403
    assert b"Access Forbidden" in response.data
