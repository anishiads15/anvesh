import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from extensions import db


class AuditEvent(db.Base):
    """Immutable audit trail for monitoring governance and administrative compliance."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_name = Column(String(120), nullable=False)
    actor_role = Column(String(80), nullable=False)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(100), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationship
    actor = relationship("User")

    @property
    def metadata_dict(self):
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except Exception:
            return {"raw": self.metadata_json}

    def to_dict(self):
        return {
            "id": self.id,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "metadata": self.metadata_dict,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    def __repr__(self):
        return f"<AuditEvent {self.action} on {self.entity_type} {self.entity_id} by {self.actor_name}>"
