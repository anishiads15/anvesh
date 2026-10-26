import pytest
from datetime import datetime
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from models.audit import AuditEvent


def test_human_confirmation_workflow(client, reviewer_user, sample_institution, db_session):
    """Test reviewer confirming a suggested overlap relationship."""
    client.post("/login", data={"username": "reviewer_test", "password": "ReviewerPass123"})

    c1 = Complaint(
        reference_number="AICTE-2026-CMP-REV1",
        title="Lab testing apparatus out of order",
        description="Testing machines broken in mechanical laboratory.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
    )
    c2 = Complaint(
        reference_number="AICTE-2026-CMP-REV2",
        title="Laboratory machines not working for experiments",
        description="Students cannot perform experiments as lab equipment is broken.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    rel = OverlapRelationship(
        first_complaint_id=min(c1.id, c2.id),
        second_complaint_id=max(c1.id, c2.id),
        similarity_score=0.85,
        relationship_type="Strong Potential Overlap",
        review_status="Pending Review",
        matching_evidence='{"summary": "Both complaints report equipment failure in the same laboratory."}',
    )
    db_session.add(rel)
    db_session.commit()

    # Reviewer confirms relationship
    response = client.post(f"/overlaps/{rel.id}/review", data={
        "action": "confirm",
        "review_notes": "Confirmed: Both refer to the identical equipment breakdown incident."
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"confirmed as related by human reviewer" in response.data

    updated_rel = db_session.query(OverlapRelationship).get(rel.id)
    assert updated_rel.review_status == "Confirmed Related"
    assert updated_rel.relationship_type == "Human-Confirmed Related"
    assert updated_rel.reviewer_id == reviewer_user.id
    assert updated_rel.reviewed_at is not None
    assert "identical equipment breakdown" in updated_rel.review_notes

    # Verify complaints are NOT merged or deleted
    assert db_session.query(Complaint).get(c1.id) is not None
    assert db_session.query(Complaint).get(c2.id) is not None

    # Verify audit event
    audit = db_session.query(AuditEvent).filter_by(action="OVERLAP_REVIEWED").first()
    assert audit is not None
    assert audit.metadata_dict.get("new_status") == "Confirmed Related"


def test_human_rejection_workflow(client, reviewer_user, sample_institution, db_session):
    """Test reviewer rejecting a potential overlap as not related."""
    client.post("/login", data={"username": "reviewer_test", "password": "ReviewerPass123"})

    c1 = Complaint(
        reference_number="AICTE-2026-CMP-REJ1",
        title="First issue",
        description="Issue description one.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
    )
    c2 = Complaint(
        reference_number="AICTE-2026-CMP-REJ2",
        title="Second issue",
        description="Issue description two.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    rel = OverlapRelationship(
        first_complaint_id=min(c1.id, c2.id),
        second_complaint_id=max(c1.id, c2.id),
        similarity_score=0.55,
        relationship_type="Possible Overlap",
        review_status="Pending Review",
        matching_evidence='{"summary": "Possible overlap in infrastructure."}',
    )
    db_session.add(rel)
    db_session.commit()

    response = client.post(f"/overlaps/{rel.id}/review", data={
        "action": "reject",
        "review_notes": "Distinct issues in separate blocks."
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"marked as NOT related" in response.data

    updated_rel = db_session.query(OverlapRelationship).get(rel.id)
    assert updated_rel.review_status == "Rejected Not Related"
    assert updated_rel.relationship_type == "Human-Confirmed Not Related"
