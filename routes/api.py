from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from extensions import db
from models.complaint import Complaint, ComplaintStatusHistory
from models.institution import Institution
from models.user import User
from models.overlap import OverlapRelationship
from models.notification import Notification
from models.audit import AuditEvent
from routes.auth import login_required, role_required, get_current_user
from services.audit_service import log_audit_event
from services.routing_service import suggest_department_routing
from services.overlap_detection import evaluate_complaint_against_all

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/complaints", methods=["GET"])
@login_required
def list_complaints():
    user = g.current_user
    query = db.session.query(Complaint)

    # 1. Complainant role isolation: strictly own complaints
    if user.is_complainant:
        query = query.filter(
            (Complaint.complainant_user_id == user.id) |
            (Complaint.complainant_id_str == user.identifier) |
            (Complaint.complainant_name == user.display_name)
        )
    # 2. Institutional admin: strictly own institution
    elif user.is_institution_admin and user.institution_id:
        query = query.filter(Complaint.institution_id == user.institution_id)
    # 3. Bureau reviewer: filter by bureau if assigned to specific bureau
    elif user.bureau and user.bureau not in ["All", "Complainant Portal"]:
        query = query.filter(Complaint.source_bureau == user.bureau)

    # Optional query filters
    status = request.args.get("status")
    if status and status != "All":
        query = query.filter(Complaint.status == status)

    bureau = request.args.get("bureau")
    if bureau and bureau != "All":
        query = query.filter(Complaint.source_bureau == bureau)

    priority = request.args.get("priority")
    if priority and priority != "All":
        query = query.filter(Complaint.priority == priority)

    search = request.args.get("q", "").strip()
    if search:
        query = query.filter(
            (Complaint.reference_number.ilike(f"%{search}%")) |
            (Complaint.title.ilike(f"%{search}%")) |
            (Complaint.description.ilike(f"%{search}%"))
        )

    # Ordering & pagination
    query = query.order_by(Complaint.created_at.desc())
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 50, type=int)
    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()

    # Format for SENTRIX API
    def format_item(c):
        d = c.to_dict()
        d["case_id"] = c.reference_number
        d["subject"] = c.title
        d["complainant_id"] = c.complainant_id_str or (user.identifier if user.is_complainant else None)
        return d

    return jsonify({
        "items": [format_item(c) for c in items],
        "total": total,
        "page": page,
        "limit": limit,
    })


@api_bp.route("/complaints/<int:complaint_id>", methods=["GET"])
@login_required
def get_complaint(complaint_id: int):
    user = g.current_user
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        return jsonify({"detail": "Complaint not found"}), 404

    # Strict Complainant Record Isolation: tamper protection
    if user.is_complainant:
        is_owner = (
            complaint.complainant_user_id == user.id or
            (user.identifier and complaint.complainant_id_str == user.identifier) or
            (complaint.complainant_name and complaint.complainant_name.lower() == user.display_name.lower())
        )
        if not is_owner:
            return jsonify({"detail": "Forbidden: You are not authorized to access another complainant's record."}), 403

    # Institutional reviewer isolation
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        return jsonify({"detail": "Forbidden: You cannot access grievances from other institutions."}), 403

    data = complaint.to_dict()
    data["case_id"] = complaint.reference_number
    data["subject"] = complaint.title
    data["complainant_id"] = complaint.complainant_id_str
    data["evidence_files"] = [complaint.attachment_filename] if complaint.attachment_filename else []
    return jsonify(data)


@api_bp.route("/complaints", methods=["POST"])
@login_required
def create_complaint():
    user = g.current_user
    data = request.get_json(silent=True) or request.form

    title = data.get("subject") or data.get("title", "").strip()
    description = data.get("description", "").strip()
    category = data.get("category", "Other")
    priority = data.get("priority", "Medium")
    inst_id = data.get("institution_id")

    if not title or not description:
        return jsonify({"detail": "Subject and description are required."}), 400

    if not inst_id:
        first_inst = db.session.query(Institution).first()
        inst_id = first_inst.id if first_inst else 1

    year = datetime.utcnow().year
    count = db.session.query(Complaint).count()
    bureau_tag = "PGRC"
    ref = f"AICTE-{year}-{bureau_tag}-{(count + 1):04d}"

    # Auto-routing
    routing = suggest_department_routing(title, description, category, "")

    c = Complaint(
        reference_number=ref,
        title=title,
        description=description,
        category=category,
        priority=priority,
        status="Submitted",
        institution_id=int(inst_id),
        source_bureau=data.get("source_bureau") or "PGRC (Public Grievance Redressal)",
        complainant_user_id=user.id if user.is_complainant else None,
        complainant_name=user.display_name if user.is_complainant else data.get("complainant_name", "Anonymous"),
        complainant_id_str=user.identifier if user.is_complainant else None,
        is_confidential=bool(data.get("is_anonymous", False)),
        suggested_destination=routing["suggested_destination"],
        routing_reason=routing["routing_reason"],
        routing_confidence=routing["confidence_score"],
        routing_requires_human_review=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(c)
    db.session.commit()

    # Recalculate overlaps
    evaluate_complaint_against_all(c, db.session, auto_save=True)

    # Log audit
    log_audit_event(
        db.session,
        actor=user,
        action="COMPLAINT_CREATED_API",
        entity_type="Complaint",
        entity_id=c.reference_number,
        metadata={"category": category, "priority": priority},
    )
    db.session.commit()

    res = c.to_dict()
    res["case_id"] = c.reference_number
    return jsonify(res), 201


@api_bp.route("/overlaps", methods=["GET"])
@login_required
def list_overlaps():
    user = g.current_user
    # Overlap intelligence restricted strictly to administrators
    if not (user.is_super_admin or user.is_aicte_officer):
        return jsonify({"detail": "Forbidden: Global overlap intelligence is restricted to administrators."}), 403

    query = db.session.query(OverlapRelationship)
    status_filter = request.args.get("status")
    if status_filter:
        query = query.filter(OverlapRelationship.review_status == status_filter)

    overlaps = query.order_by(OverlapRelationship.similarity_score.desc()).limit(100).all()
    return jsonify({
        "items": [o.to_dict() for o in overlaps],
        "total": len(overlaps),
    })


@api_bp.route("/overlaps/<int:overlap_id>/review", methods=["POST"])
@login_required
def review_overlap(overlap_id: int):
    user = g.current_user
    if user.is_complainant or user.is_auditor:
        return jsonify({"detail": "Forbidden: Insufficient permissions to review overlaps."}), 403

    overlap = db.session.query(OverlapRelationship).get(overlap_id)
    if not overlap:
        return jsonify({"detail": "Overlap not found"}), 404

    data = request.get_json(silent=True) or request.form
    decision = data.get("decision") or data.get("action")  # CONFIRM_LINK, JOINT_INVESTIGATION, DISMISS_FALSE_POSITIVE, confirm, reject
    remarks = data.get("remarks") or data.get("review_notes", "")

    if decision in ["CONFIRM_LINK", "confirm", "JOINT_INVESTIGATION", "TRANSFER_BUREAU", "CONFIRM_DUPLICATE"]:
        overlap.review_status = "Confirmed Related"
        overlap.relationship_type = "Human-Confirmed Related"
    elif decision in ["DISMISS_FALSE_POSITIVE", "reject", "SEPARATE_INVESTIGATION"]:
        overlap.review_status = "Rejected Not Related"
        overlap.relationship_type = "Human-Confirmed Not Related"

    overlap.reviewer_id = user.id
    overlap.review_notes = remarks
    overlap.reviewed_at = datetime.utcnow()

    log_audit_event(
        db.session,
        actor=user,
        action="OVERLAP_DECISION_API",
        entity_type="OverlapRelationship",
        entity_id=str(overlap.id),
        metadata={"decision": decision, "remarks": remarks},
    )
    db.session.commit()

    return jsonify({"message": "Overlap decision recorded successfully.", "overlap": overlap.to_dict()})


@api_bp.route("/dashboard", methods=["GET"])
@login_required
def get_dashboard():
    user = g.current_user
    now = datetime.utcnow()

    # Complainant personal stats
    if user.is_complainant:
        user_cases = db.session.query(Complaint).filter(
            (Complaint.complainant_user_id == user.id) |
            (Complaint.complainant_id_str == user.identifier) |
            (Complaint.complainant_name == user.display_name)
        ).all()

        total = len(user_cases)
        resolved = sum(1 for c in user_cases if c.status in ["Resolved", "Closed", "Disposed"])
        under_review = total - resolved

        return jsonify({
            "is_complainant": True,
            "total_grievances": total,
            "resolved_grievances": resolved,
            "under_review_grievances": max(0, under_review),
            "recent_cases": [c.to_dict() for c in user_cases[:5]],
        })

    # Central / Admin / Reviewer metrics
    total_complaints = db.session.query(Complaint).count()
    resolved_count = db.session.query(Complaint).filter(Complaint.status.in_(["Resolved", "Closed", "Disposed"])).count()
    under_investigation = db.session.query(Complaint).filter(Complaint.status.in_(["Under Investigation", "Joint Investigation"])).count()
    under_review = db.session.query(Complaint).filter(Complaint.status.in_(["Under Institutional Review", "Under Review", "Pending Bureau Review"])).count()
    escalated = db.session.query(Complaint).filter(Complaint.status.in_(["Escalated to AICTE", "Escalated", "Escalated to Committee"])).count()
    submitted = db.session.query(Complaint).filter(Complaint.status.in_(["Submitted", "New", "Open"])).count()
    under_process = max(0, total_complaints - resolved_count)

    active_overlaps = db.session.query(OverlapRelationship).filter(OverlapRelationship.review_status == "Pending Review").count()
    confirmed_overlaps = db.session.query(OverlapRelationship).filter(OverlapRelationship.review_status == "Confirmed Related").count()

    # Overdue count
    overdue_count = db.session.query(Complaint).filter(
        ~Complaint.status.in_(["Resolved", "Closed", "Disposed"]),
        Complaint.due_date < now,
    ).count()

    return jsonify({
        "total_cases": total_complaints,
        "resolved_cases": resolved_count,
        "under_process_cases": under_process,
        "under_review_cases": under_review,
        "under_investigation_cases": under_investigation,
        "escalated_cases": escalated,
        "submitted_cases": submitted,
        "active_overlaps": active_overlaps,
        "confirmed_overlaps": confirmed_overlaps,
        "overdue_cases": overdue_count,
        "sla_compliance_rate": round(max(0, (total_complaints - overdue_count) / max(1, total_complaints)) * 100, 1),
    })


@api_bp.route("/reports", methods=["GET"])
@login_required
def get_reports():
    user = g.current_user
    if user.is_complainant:
        return jsonify({"detail": "Forbidden: Complainants cannot access central audit reports."}), 403

    # Bureau-wise distribution
    bureaus = {}
    for b, count in db.session.query(Complaint.source_bureau, db.func.count(Complaint.id)).group_by(Complaint.source_bureau).all():
        if b:
            bureaus[b] = count

    # Category distribution
    categories = {}
    for cat, count in db.session.query(Complaint.category, db.func.count(Complaint.id)).group_by(Complaint.category).all():
        categories[cat] = count

    return jsonify({
        "bureau_breakdown": bureaus,
        "category_breakdown": categories,
        "generated_at": datetime.utcnow().isoformat(),
    })


@api_bp.route("/notifications", methods=["GET"])
@login_required
def list_notifications():
    user = g.current_user
    query = db.session.query(Notification)

    if user.is_complainant:
        c_id = user.identifier or user.username
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        user_c_ids = [c[0] for c in db.session.query(Complaint.id).filter(
            (Complaint.complainant_user_id == user.id) |
            (Complaint.complainant_id_str == user.identifier) |
            (Complaint.complainant_name == user.display_name)
        ).all()]
        query = query.filter(
            (Notification.complainant_id == c_id) |
            (Notification.complaint_id.in_(user_c_ids) if user_c_ids else False)
        )
    elif user.is_institution_admin and user.institution_id:
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        inst_c_ids = [c[0] for c in db.session.query(Complaint.id).filter(
            Complaint.institution_id == user.institution_id
        ).all()]
        query = query.filter(Notification.complaint_id.in_(inst_c_ids) if inst_c_ids else False)
    elif not (user.is_super_admin or user.is_aicte_officer):
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        if user.bureau and user.bureau not in ["All", "Complainant Portal"]:
            query = query.filter((Notification.bureau == user.bureau) | (Notification.bureau == "All"))

    notifs = query.order_by(Notification.created_at.desc()).limit(30).all()
    items = [n.to_dict() for n in notifs]
    return jsonify({
        "items": items,
        "notifications": items,
        "unread_count": sum(1 for n in notifs if not n.is_read),
    })


@api_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    user = g.current_user
    query = db.session.query(Notification).filter_by(is_read=False)

    if user.is_complainant:
        c_id = user.identifier or user.username
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        user_c_ids = [c[0] for c in db.session.query(Complaint.id).filter(
            (Complaint.complainant_user_id == user.id) |
            (Complaint.complainant_id_str == user.identifier) |
            (Complaint.complainant_name == user.display_name)
        ).all()]
        query = query.filter(
            (Notification.complainant_id == c_id) |
            (Notification.complaint_id.in_(user_c_ids) if user_c_ids else False)
        )
    elif user.is_institution_admin and user.institution_id:
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        inst_c_ids = [c[0] for c in db.session.query(Complaint.id).filter(
            Complaint.institution_id == user.institution_id
        ).all()]
        query = query.filter(Notification.complaint_id.in_(inst_c_ids) if inst_c_ids else False)
    elif not (user.is_super_admin or user.is_aicte_officer):
        query = query.filter(Notification.type != "OVERLAP_DETECTED")
        if user.bureau and user.bureau not in ["All", "Complainant Portal"]:
            query = query.filter((Notification.bureau == user.bureau) | (Notification.bureau == "All"))

    unread_items = query.all()
    for n in unread_items:
        n.is_read = True
    db.session.commit()
    return jsonify({"success": True, "marked_count": len(unread_items)})


@api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id: int):
    n = db.session.query(Notification).get(notification_id)
    if n:
        n.is_read = True
        db.session.commit()
    return jsonify({"success": True})
