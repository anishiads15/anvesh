from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from extensions import db


class RelatedComplaintGroup(db.Base):
    """Shared issue group linking multiple individual complaints that describe the same underlying incident."""

    __tablename__ = "related_complaint_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_reference = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    category = Column(String(100), nullable=False, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="Open", index=True)  # Open, Under Review, Partially Resolved, Resolved, Reopened
    resolution_summary = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    institution = relationship("Institution")
    resolved_by = relationship("User", foreign_keys=[resolved_by_user_id])
    complaints = relationship("Complaint", back_populates="related_group")

    @property
    def total_complaints(self) -> int:
        return len(self.complaints)

    @property
    def resolved_complaints_count(self) -> int:
        return sum(1 for c in self.complaints if c.status in ["Resolved", "Closed"])

    def to_dict(self):
        return {
            "id": self.id,
            "group_reference": self.group_reference,
            "title": self.title,
            "description": self.description,
            "root_cause": self.root_cause,
            "category": self.category,
            "institution_id": self.institution_id,
            "institution_name": self.institution.name if self.institution else "Cross-Institution",
            "status": self.status,
            "total_complaints": self.total_complaints,
            "resolved_complaints_count": self.resolved_complaints_count,
            "resolution_summary": self.resolution_summary,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<RelatedComplaintGroup {self.group_reference}: {self.title[:30]}>"
