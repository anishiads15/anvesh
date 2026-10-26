import json
import logging
from datetime import datetime
from models.audit import AuditEvent

logger = logging.getLogger(__name__)


def log_audit_event(session, actor, action: str, entity_type: str, entity_id=None, metadata: dict = None) -> AuditEvent:
    """Records an immutable audit event in the system log.
    
    Args:
        session: Active SQLAlchemy session
        actor: User object or None (e.g. system action or anonymous user)
        action: Identifier like "COMPLAINT_CREATED", "STATUS_CHANGED", "OVERLAP_REVIEWED"
        entity_type: "Complaint", "OverlapRelationship", "Institution", "User", "Auth", "Report"
        entity_id: String ID or reference number of target
        metadata: Optional dictionary with change context
    """
    actor_id = getattr(actor, "id", None)
    actor_name = getattr(actor, "display_name", "System / Automated Engine")
    actor_role = getattr(actor, "role_title", lambda: getattr(actor, "role", "System"))()

    metadata_json = json.dumps(metadata) if metadata else None

    event = AuditEvent(
        actor_id=actor_id,
        actor_name=actor_name,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        metadata_json=metadata_json,
        timestamp=datetime.utcnow(),
    )

    try:
        session.add(event)
        session.flush()
        return event
    except Exception as e:
        logger.error(f"Failed to record audit event {action}: {e}")
        return None
