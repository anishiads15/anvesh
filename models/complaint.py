from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from extensions import db


class Complaint(db.Base):
    """Educational institution complaint record."""

    __tablename__ = "complaints"

    CATEGORIES = [
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
        # Extended SENTRIX taxonomies
        "Fee Overcharging / Capitation",
        "Infrastructure & Laboratory Deficit",
        "Withholding Original Certificates",
        "Admissions & Affiliation Irregularities",
        "Governance Malpractice & Retaliation",
        "Misappropriation of Grant Funds",
        "Faculty Non-Payment & Understaffing",
        "Unapproved Courses & Excess Intake",
    ]

    # Backward compatibility aliases for earlier taxonomy names
    LEGACY_CATEGORIES = [
        "Infrastructure",
        "Laboratory and equipment",
        "Faculty and staffing",
        "Academic quality",
        "Student facilities",
        "Safety and accessibility",
        "Administrative compliance",
    ]

    PRIORITIES = ["Low", "Medium", "High", "Critical", "Urgent"]
    STATUSES = [
        "Submitted",
        "Acknowledged",
        "Under Institutional Review",
        "Under Review",
        "Escalated to AICTE",
        "Under Investigation",
        "Returned for Action",
        "Resolved",
        "Closed",
        "Reopened",
        "Open",
        "Pending",
        "Escalated",
        # Additional SENTRIX statutory workflow statuses
        "New",
        "Pending Bureau Review",
        "Hearing Scheduled",
        "Action Taken Report Awaited",
        "Disposed",
        "Joint Investigation",
        "Transferred",
        "Under Process",
    ]

    BUREAUS = [
        "PGRC (Public Grievance Redressal)",
        "Regulation Bureau (RB)",
        "Approval Bureau (AB)",
        "Policy & Academic Planning Bureau (PAPB)",
        "Anti-Ragging Cell (ARC)",
        "Skill Development Cell (SDC)",
        "Institutional Redressal Cell",
        "All",
    ]

    SOURCES = [
        "Student grievance",
        "Institutional report",
        "Inspection report",
        "Public grievance",
        "Faculty report",
        "Confidential report",
        "Other",
        "Student",
        "Faculty",
        "Parent / Guardian",
        "Anonymous Whistleblower",
    ]

    id = Column(Integer, primary_key=True, autoincrement=True)
    reference_number = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    institution_id = Column(Integer, ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_channel = Column(String(100), nullable=False, default="Student grievance")
    category = Column(String(100), nullable=False, index=True)
    subcategory = Column(String(100), nullable=True)
    priority = Column(String(50), nullable=False, default="Medium", index=True)
    status = Column(String(50), nullable=False, default="Open", index=True)
    assigned_reviewer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    complainant_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    complainant_name = Column(String(120), nullable=True)
    is_confidential = Column(Boolean, default=False, nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False, index=True)
    official_remarks = Column(Text, nullable=True)
    aicte_remarks = Column(Text, nullable=True)
    public_resolution_statement = Column(Text, nullable=True)
    escalation_reason = Column(Text, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    attachment_filename = Column(String(255), nullable=True)
    feedback_rating = Column(Integer, nullable=True)
    feedback_notes = Column(Text, nullable=True)
    reopen_reason = Column(Text, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolution_date = Column(DateTime, nullable=True)
    supporting_reference = Column(String(255), nullable=True)
    categorization_source = Column(String(100), default="Manual Selection")
    categorization_confidence = Column(Float, nullable=True)

    # AI-Assisted Department Routing
    suggested_destination = Column(String(50), nullable=True, index=True)  # PGRC, RC, Institutional Reviewer, Manual Review
    routing_reason = Column(Text, nullable=True)
    routing_confidence = Column(Float, nullable=True)
    routing_requires_human_review = Column(Boolean, default=True, nullable=False)
    routed_destination = Column(String(50), nullable=True, index=True)  # Confirmed destination
    routed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    routed_at = Column(DateTime, nullable=True)
    routing_decision = Column(String(50), nullable=True)  # Accepted, Modified, Pending
    routing_override_reason = Column(Text, nullable=True)

    # Shared Related Complaint Group & Detailed Resolution Tracking
    related_group_id = Column(Integer, ForeignKey("related_complaint_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    resolution_status = Column(String(50), default="Not Yet Resolved", nullable=False, index=True)  # Not Yet Resolved, Resolved, Partially Resolved, Reopened
    is_recurrence = Column(Boolean, default=False, nullable=False)
    recurrence_notes = Column(Text, nullable=True)

    # Extended SENTRIX SIH26264 Fields for Cross-Bureau Governance & SLA
    source_bureau = Column(String(100), nullable=True, index=True)
    due_date = Column(DateTime, nullable=True, index=True)
    incident_date = Column(DateTime, nullable=True)
    complainant_id_str = Column(String(80), nullable=True, index=True)
    assigned_officer_name = Column(String(120), nullable=True)
    last_action_date = Column(DateTime, nullable=True)
    next_action_due = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    institution = relationship("Institution", back_populates="complaints")
    assigned_reviewer = relationship("User", back_populates="assigned_complaints", foreign_keys=[assigned_reviewer_id])
    complainant_user = relationship("User", back_populates="filed_complaints", foreign_keys=[complainant_user_id])
    routed_by = relationship("User", foreign_keys=[routed_by_user_id])
    related_group = relationship("RelatedComplaintGroup", back_populates="complaints", foreign_keys=[related_group_id])

    status_history = relationship(
        "ComplaintStatusHistory",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="ComplaintStatusHistory.timestamp.asc()",
    )

    overlaps_as_first = relationship(
        "OverlapRelationship",
        foreign_keys="OverlapRelationship.first_complaint_id",
        back_populates="first_complaint",
        cascade="all, delete-orphan",
    )
    overlaps_as_second = relationship(
        "OverlapRelationship",
        foreign_keys="OverlapRelationship.second_complaint_id",
        back_populates="second_complaint",
        cascade="all, delete-orphan",
    )

    @property
    def all_overlaps(self):
        """Returns all overlap relationships involving this complaint."""
        return list(self.overlaps_as_first) + list(self.overlaps_as_second)

    @property
    def display_complainant(self) -> str:
        """Masks complainant name if confidential flag is active."""
        if self.is_confidential:
            return "[CONFIDENTIAL COMPLAINANT]"
        if self.complainant_name:
            return self.complainant_name
        if self.complainant_user:
            return self.complainant_user.display_name
        return "Anonymous Complainant"

    @property
    def is_overdue(self) -> bool:
        """Determines if grievance is past its statutory resolution SLA."""
        if self.status in ["Resolved", "Closed", "Disposed"]:
            return False
        if self.due_date and self.due_date < datetime.utcnow():
            return True
        # Default SLA: 30 days from creation if no due_date
        from datetime import timedelta
        if (datetime.utcnow() - self.created_at) > timedelta(days=30):
            return True
        return False

    @property
    def days_open(self) -> int:
        end = self.resolution_date or datetime.utcnow()
        return max(0, (end - self.created_at).days)

    @property
    def highest_overlap_badge(self) -> str:
        """Returns the highest-priority overlap status indicator for badges and highlights."""
        if any(o.review_status == "Confirmed Related" for o in self.all_overlaps):
            return "CONFIRMED_RELATED"
        if any(o.relationship_type == "Strong Potential Overlap" and o.review_status == "Pending Review" for o in self.all_overlaps):
            return "STRONG_POTENTIAL"
        if any(o.relationship_type == "Possible Overlap" and o.review_status == "Pending Review" for o in self.all_overlaps):
            return "POSSIBLE_OVERLAP"
        return "NONE"

    def to_dict(self):
        return {
            "id": self.id,
            "reference_number": self.reference_number,
            "title": self.title,
            "description": self.description,
            "institution_id": self.institution_id,
            "institution_name": self.institution.name if self.institution else None,
            "institution_code": self.institution.code if self.institution else None,
            "source_channel": self.source_channel,
            "source_bureau": self.source_bureau,
            "category": self.category,
            "subcategory": self.subcategory,
            "priority": self.priority,
            "status": self.status,
            "complainant": self.display_complainant,
            "complainant_id_str": self.complainant_id_str,
            "is_confidential": self.is_confidential,
            "is_demo": self.is_demo,
            "assigned_reviewer": self.assigned_reviewer.display_name if self.assigned_reviewer else self.assigned_officer_name,
            "complainant_user_id": self.complainant_user_id,
            "official_remarks": self.official_remarks,
            "aicte_remarks": self.aicte_remarks,
            "public_resolution_statement": self.public_resolution_statement,
            "escalation_reason": self.escalation_reason,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "attachment_filename": self.attachment_filename,
            "feedback_rating": self.feedback_rating,
            "feedback_notes": self.feedback_notes,
            "reopen_reason": self.reopen_reason,
            "resolution_notes": self.resolution_notes,
            "resolution_date": self.resolution_date.isoformat() if self.resolution_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "is_overdue": self.is_overdue,
            "days_open": self.days_open,
            "categorization_source": self.categorization_source,
            "categorization_confidence": self.categorization_confidence,
            "suggested_destination": self.suggested_destination,
            "routing_reason": self.routing_reason,
            "routing_confidence": self.routing_confidence,
            "routing_requires_human_review": self.routing_requires_human_review,
            "routed_destination": self.routed_destination,
            "routed_by": self.routed_by.display_name if self.routed_by else None,
            "routed_at": self.routed_at.isoformat() if self.routed_at else None,
            "routing_decision": self.routing_decision,
            "routing_override_reason": self.routing_override_reason,
            "related_group_id": self.related_group_id,
            "related_group_ref": self.related_group.group_reference if self.related_group else None,
            "related_group_title": self.related_group.title if self.related_group else None,
            "resolution_status": self.resolution_status,
            "is_recurrence": self.is_recurrence,
            "recurrence_notes": self.recurrence_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "overlap_badge": self.highest_overlap_badge,
        }

    def __repr__(self):
        return f"<Complaint {self.reference_number}: {self.title[:30]}>"


class ComplaintStatusHistory(db.Base):
    """Audit log of status changes for a complaint."""

    __tablename__ = "complaint_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String(120), nullable=False)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    complaint = relationship("Complaint", back_populates="status_history")
    actor = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "complaint_id": self.complaint_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "actor_name": self.actor_name,
            "notes": self.notes,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
