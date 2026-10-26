from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from extensions import db


class Notification(db.Base):
    """System and role-based notification entity."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False, default="GENERAL")
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="info")  # info, warning, critical, success
    complaint_id = Column(Integer, ForeignKey("complaints.id", ondelete="CASCADE"), nullable=True, index=True)
    bureau = Column(String(100), nullable=True, index=True)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    complainant_id = Column(String(80), nullable=True, index=True)
    recipient_role = Column(String(50), nullable=True, index=True)

    # Relationships
    complaint = relationship("Complaint")

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "event_type": self.type,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "complaint_id": self.complaint_id,
            "bureau": self.bureau,
            "is_read": self.is_read,
            "created_at": self.created_at.strftime("%d %b %Y, %H:%M") if self.created_at else None,
            "complainant_id": self.complainant_id,
        }

    def __repr__(self):
        return f"<Notification {self.id}: {self.title[:30]}>"
