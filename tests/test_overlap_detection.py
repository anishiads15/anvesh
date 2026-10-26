import pytest
from datetime import datetime
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from services.overlap_detection import (
    calculate_overlap_score,
    evaluate_complaint_against_all,
)


def test_strong_potential_overlap_different_wording(sample_institution):
    """Test core innovation: detects two complaints describing the same underlying laboratory failure
    despite completely distinct phrasing and vocabulary.
    """
    c_a = Complaint(
        id=1,
        reference_number="AICTE-2026-CMP-0001",
        title="The mechanical laboratory's testing equipment has remained non-functional for two weeks.",
        description="Workshop machinery and tensile testing apparatus have broken down, severely disrupting lab work.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Under Review",
        created_at=datetime.utcnow(),
    )

    c_b = Complaint(
        id=2,
        reference_number="AICTE-2026-CMP-0002",
        title="Students cannot conduct practical experiments because the department's lab machines are broken.",
        description="Students cannot conduct practical experiments because the mechanical department's lab machines and apparatus are broken down and completely out of order.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
        created_at=datetime.utcnow(),
    )

    # Test with AI SentenceTransformer (detects semantic similarity despite disparate wording)
    result_ai = calculate_overlap_score(c_a, c_b, allow_transformer=True)
    assert result_ai["similarity_score"] >= 0.50
    assert result_ai["relationship_type"] in ["Strong Potential Overlap", "Possible Overlap"]

    # Test with documented TF-IDF fallback method (returns score & shared keywords)
    result_fallback = calculate_overlap_score(c_a, c_b, allow_transformer=False)
    assert result_fallback["similarity_score"] > 0.35
    assert "lab" in result_fallback["evidence_dict"]["shared_keywords"] or "apparatus" in result_fallback["evidence_dict"]["shared_keywords"] or "broken" in result_fallback["evidence_dict"]["shared_keywords"]
    assert result_fallback["category_score"] == 1.0
    assert "Fallback" in result_fallback["algorithm_version"]


def test_unrelated_complaints_same_institution_not_flagged(sample_institution):
    """CRITICAL TEST: Complaint C (drinking water) at the same institution as Complaint A (lab machines)
    must NOT be marked as an overlap merely because the institution is identical!
    """
    c_lab = Complaint(
        id=1,
        reference_number="AICTE-2026-CMP-0001",
        title="The mechanical laboratory's testing equipment has remained non-functional for two weeks.",
        description="Workshop machinery and tensile testing apparatus have broken down, severely disrupting lab work.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
        created_at=datetime.utcnow(),
    )

    c_water = Complaint(
        id=3,
        reference_number="AICTE-2026-CMP-0003",
        title="The college drinking-water purifier is not functioning.",
        description="The drinking water purifier facility in block B is broken and leaking unhygienic water.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
        created_at=datetime.utcnow(),
    )

    result = calculate_overlap_score(c_lab, c_water, allow_transformer=False)

    # Score MUST be well below the overlap threshold of 0.50
    assert result["similarity_score"] < 0.50
    assert result["relationship_type"] == "No Overlap"
    # Verify contradictory topic detection suppressed the score
    assert result["conflicting_evidence"] is not None


def test_cross_institution_similar_complaints(sample_institution, sample_institution_2):
    """Test complaints with similar content from DIFFERENT institutions do not get elevated context score."""
    c_inst1 = Complaint(
        id=10,
        reference_number="AICTE-2026-CMP-0010",
        title="Physics lab equipment broken",
        description="Oscilloscopes and power supplies in physics lab are broken down.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
        created_at=datetime.utcnow(),
    )

    c_inst2 = Complaint(
        id=11,
        reference_number="AICTE-2026-CMP-0011",
        title="Physics lab instruments damaged",
        description="Oscilloscopes and apparatus in physics laboratory need urgent replacement.",
        institution_id=sample_institution_2.id,
        category="Laboratory and equipment",
        status="Open",
        created_at=datetime.utcnow(),
    )

    result = calculate_overlap_score(c_inst1, c_inst2, allow_transformer=False)

    # Context score should reflect that they are from different institutions
    assert result["evidence_dict"]["same_institution"] is False
    assert result["context_score"] <= 0.35


def test_canonical_ordering_and_no_duplicates(db_session, sample_institution):
    """Test overlap evaluator maintains canonical pair ordering (c1.id < c2.id)
    and prevents duplicate pair creation.
    """
    c1 = Complaint(
        reference_number="AICTE-2026-CMP-CANON1",
        title="Mechanical lab testing machines broken",
        description="Machines and testing apparatus in mechanical laboratory are broken down and completely non functional.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
    )
    c2 = Complaint(
        reference_number="AICTE-2026-CMP-CANON2",
        title="Mechanical lab equipment non functional",
        description="Laboratory equipment and machinery in mechanical testing lab is non-functional and broken down.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Open",
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    # Evaluate overlaps
    evaluate_complaint_against_all(c2, db_session, allow_transformer=False)

    # Check that relationship is stored canonically: first_id < second_id
    rel = db_session.query(OverlapRelationship).first()
    assert rel is not None
    assert rel.first_complaint_id == min(c1.id, c2.id)
    assert rel.second_complaint_id == max(c1.id, c2.id)
    assert rel.similarity_score >= 0.50

    # Running evaluation again should NOT duplicate the record
    evaluate_complaint_against_all(c1, db_session, allow_transformer=False)
    total_rels = db_session.query(OverlapRelationship).count()
    assert total_rels == 1
