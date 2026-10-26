import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from extensions import db


class OverlapRelationship(db.Base):
    """Potential or confirmed duplicate/overlap relationship between two complaints."""

    __tablename__ = "overlap_relationships"

    TYPES = [
        "Strong Potential Overlap",
        "Possible Overlap",
        "Human-Confirmed Related",
        "Human-Confirmed Not Related",
    ]

    REVIEW_STATUSES = ["Pending Review", "Confirmed Related", "Rejected Not Related"]

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    second_complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score = Column(Float, nullable=False, index=True)
    semantic_score = Column(Float, nullable=False, default=0.0)
    keyword_score = Column(Float, nullable=False, default=0.0)
    category_score = Column(Float, nullable=False, default=0.0)
    context_score = Column(Float, nullable=False, default=0.0)
    relationship_type = Column(String(50), nullable=False, default="Possible Overlap", index=True)
    review_status = Column(String(50), nullable=False, default="Pending Review", index=True)
    matching_evidence = Column(Text, nullable=False)
    conflicting_evidence = Column(Text, nullable=True)
    algorithm_version = Column(String(100), nullable=False, default="v2.0-hybrid")
    reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    # Ensure canonical ordering and prevent duplicate pairs
    __table_args__ = (
        UniqueConstraint("first_complaint_id", "second_complaint_id", name="uq_complaint_pair"),
        CheckConstraint("first_complaint_id < second_complaint_id", name="ck_canonical_pair_order"),
    )

    # Relationships
    first_complaint = relationship("Complaint", foreign_keys=[first_complaint_id], back_populates="overlaps_as_first")
    second_complaint = relationship("Complaint", foreign_keys=[second_complaint_id], back_populates="overlaps_as_second")
    reviewer = relationship("User", back_populates="reviewed_overlaps")

    @property
    def evidence_data(self):
        try:
            return json.loads(self.matching_evidence)
        except Exception:
            return {"summary": self.matching_evidence, "keywords": [], "explanation": self.matching_evidence}

    def to_dict(self):
        return {
            "id": self.id,
            "first_complaint_id": self.first_complaint_id,
            "first_complaint_ref": self.first_complaint.reference_number if self.first_complaint else None,
            "first_complaint_title": self.first_complaint.title if self.first_complaint else None,
            "second_complaint_id": self.second_complaint_id,
            "second_complaint_ref": self.second_complaint.reference_number if self.second_complaint else None,
            "second_complaint_title": self.second_complaint.title if self.second_complaint else None,
            "institution_name": self.first_complaint.institution.name if self.first_complaint and self.first_complaint.institution else None,
            "same_institution": (self.first_complaint.institution_id == self.second_complaint.institution_id) if (self.first_complaint and self.second_complaint) else False,
            "similarity_score": round(self.similarity_score, 4),
            "similarity_percentage": round(self.similarity_score * 100, 1),
            "semantic_score": round(self.semantic_score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "category_score": round(self.category_score, 4),
            "context_score": round(self.context_score, 4),
            "relationship_type": self.relationship_type,
            "review_status": self.review_status,
            "evidence": self.evidence_data,
            "conflicting_evidence": self.conflicting_evidence,
            "algorithm_version": self.algorithm_version,
            "reviewer_name": self.reviewer.display_name if self.reviewer else None,
            "review_notes": self.review_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }

    def __repr__(self):
        return f"<OverlapRelationship {self.first_complaint_id}<->{self.second_complaint_id}: {self.similarity_score:.2f} ({self.review_status})>"
