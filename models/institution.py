from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from extensions import db


class Institution(db.Base):
    """Educational Institution registered in the AICTE Monitoring System."""

    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    institution_type = Column(String(100), nullable=False, default="Engineering College")
    state = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)
    contact_person = Column(String(120), nullable=True)
    contact_email = Column(String(120), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Extended SENTRIX Permanent Registration Fields
    aicte_id = Column(String(64), nullable=True, index=True)
    normalized_name = Column(String(255), nullable=True, index=True)
    region = Column(String(64), nullable=True)
    address = Column(Text, nullable=True)
    pincode = Column(String(16), nullable=True)
    approval_status = Column(String(32), nullable=True, default="Approved")

    # Relationships
    complaints = relationship("Complaint", back_populates="institution", cascade="all, delete-orphan")
    users = relationship("User", back_populates="institution")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "aicte_id": self.aicte_id or self.code,
            "normalized_name": self.normalized_name or self.name,
            "institution_type": self.institution_type,
            "region": self.region,
            "state": self.state,
            "district": self.district,
            "address": self.address,
            "pincode": self.pincode,
            "contact_person": self.contact_person,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "approval_status": self.approval_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "complaint_count": len(self.complaints) if self.complaints else 0,
        }

    def __repr__(self):
        return f"<Institution {self.code}: {self.name}>"
