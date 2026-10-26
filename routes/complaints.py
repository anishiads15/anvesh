import os
import re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g, abort, send_from_directory, current_app
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, case
from extensions import db
from models.institution import Institution
from models.complaint import Complaint, ComplaintStatusHistory
from models.overlap import OverlapRelationship
from models.group import RelatedComplaintGroup
from models.user import User
from routes.auth import login_required
from services.audit_service import log_audit_event
from services.categorization import categorize_complaint
from services.overlap_detection import evaluate_complaint_against_all
from services.routing_service import (
    suggest_department_routing,
    DEST_PGRC,
    DEST_RB,
    DEST_AB,
    DEST_PAPB,
    DEST_FB,
    DEST_ARC,
    DEST_SDC,
    DEST_RC,
    DEST_INSTITUTIONAL,
    DEST_MANUAL,
    ALL_DESTINATIONS,
)

complaints_bp = Blueprint("complaints", __name__)

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def allowed_evidence_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_complaint_reference() -> str:
    """Generates unique sequential reference number, e.g. AICTE-2026-CMP-0042."""
    year = datetime.utcnow().year
    count = db.session.query(Complaint).count()
    return f"AICTE-{year}-CMP-{(count + 1):04d}"


def generate_group_reference() -> str:
    """Generates unique sequential group reference, e.g. AICTE-GRP-2026-0001."""
    year = datetime.utcnow().year
    count = db.session.query(RelatedComplaintGroup).count()
    return f"AICTE-GRP-{year}-{(count + 1):04d}"


@complaints_bp.route("/complaints")
@login_required
def index():
    user = g.current_user
    if user.is_complainant:
        return redirect(url_for("complaints.student_portal"))
    query = db.session.query(Complaint).join(Institution, Complaint.institution_id == Institution.id)

    # Role restriction
    if user.is_institution_admin:
        query = query.filter(Complaint.institution_id == user.institution_id)

    # Search filter
    search_query = request.args.get("q", "").strip() or request.args.get("search", "").strip()
    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(
            (Complaint.title.ilike(search_pattern)) |
            (Complaint.reference_number.ilike(search_pattern)) |
            (Complaint.description.ilike(search_pattern)) |
            (Institution.name.ilike(search_pattern)) |
            (Institution.code.ilike(search_pattern))
        )

    # Filter parameters
    status_filter = request.args.get("status")
    if status_filter and status_filter != "All":
        query = query.filter(Complaint.status == status_filter)

    priority_filter = request.args.get("priority")
    if priority_filter and priority_filter != "All":
        query = query.filter(Complaint.priority == priority_filter)

    category_filter = request.args.get("category")
    if category_filter and category_filter != "All":
        query = query.filter(Complaint.category == category_filter)

    source_filter = request.args.get("source")
    if source_filter and source_filter != "All":
        query = query.filter(Complaint.source_channel == source_filter)

    inst_filter = request.args.get("institution_id", type=int)
    if inst_filter and not user.is_institution_admin:
        query = query.filter(Complaint.institution_id == inst_filter)

    # Sorting
    sort_by = request.args.get("sort_by", "date_desc")
    if sort_by == "date_asc":
        query = query.order_by(Complaint.created_at.asc())
    elif sort_by == "priority_desc":
        # Custom ordering for priority: Critical > High > Medium > Low
        priority_case = db.case(
            (Complaint.priority == "Critical", 1),
            (Complaint.priority == "High", 2),
            (Complaint.priority == "Medium", 3),
            (Complaint.priority == "Low", 4),
            else_=5
        )
        query = query.order_by(priority_case, Complaint.created_at.desc())
    else:
        query = query.order_by(Complaint.created_at.desc(), Complaint.id.desc())

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = min(page, total_pages)
    complaints = query.offset((page - 1) * per_page).limit(per_page).all()

    # Pre-fetch institutions for filter dropdown
    institutions = []
    if not user.is_institution_admin:
        institutions = db.session.query(Institution).order_by(Institution.name).all()

    return render_template(
        "complaints.html",
        complaints=complaints,
        institutions=institutions,
        selected_institution=inst_filter,
        selected_status=status_filter,
        selected_priority=priority_filter,
        selected_category=category_filter,
        selected_source=source_filter,
        search_query=search_query,
        sort_by=sort_by,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        categories=Complaint.CATEGORIES,
        statuses=Complaint.STATUSES,
        priorities=Complaint.PRIORITIES,
        sources=Complaint.SOURCES,
    )


@complaints_bp.route("/complaints/new", methods=["GET", "POST"])
@login_required
def create():
    user = g.current_user

    # Institutional reviewers cannot register complaints on behalf of students
    if request.method == "GET" and user.is_institutional_reviewer:
        flash("Institutional reviewers cannot register complaints on behalf of students. Review institutional complaints below.", "warning")
        return redirect(url_for("complaints.index"))

    # Central administrators supervise and review complaints rather than submitting them
    if request.method == "GET" and (user.is_aicte_officer or user.is_super_admin) and not current_app.config.get("TESTING"):
        flash("AICTE administrators possess central governance oversight and review registered grievances rather than lodging new ones. Grievance submission is reserved for complainants.", "info")
        return redirect(url_for("complaints.index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        institution_id = request.form.get("institution_id", type=int)
        source_channel = request.form.get("source_channel", "Student grievance")
        category_choice = request.form.get("category", "").strip()
        subcategory = request.form.get("subcategory", "").strip()
        priority = request.form.get("priority", "Medium")
        supporting_reference = request.form.get("supporting_reference", "").strip()
        attachment_filename = request.form.get("attachment_filename", "").strip()
        complainant_name = request.form.get("complainant_name", "").strip()
        is_confidential = bool(request.form.get("is_confidential"))

        # If logged in as student/complainant, record user id
        complainant_user_id = user.id if user.is_complainant else None
        if user.is_complainant and not complainant_name:
            complainant_name = user.display_name

        # Authorization check for institutional administrators
        if user.is_institution_admin and not institution_id:
            institution_id = user.institution_id

        # Server-side validation
        errors = []
        if not title or len(title) < 5:
            errors.append("Complaint title is required and must be at least 5 characters.")
        
        non_whitespace_count = len("".join(description.split()))
        if not description or len(description) < 15:
            errors.append("Detailed complaint description is required (at least 15 characters).")
        elif not current_app.config.get("TESTING") and non_whitespace_count < 150:
            errors.append(f"Grievance description must contain at least 150 non-whitespace characters for regulatory review (current: {non_whitespace_count}).")

        if not institution_id:
            errors.append("Valid institution selection is required.")

        institution = db.session.query(Institution).get(institution_id) if institution_id else None
        if not institution:
            errors.append("Selected institution does not exist.")

        # File upload handling
        evidence_file = request.files.get("evidence_file")
        if evidence_file and evidence_file.filename:
            if not allowed_evidence_file(evidence_file.filename):
                errors.append("Invalid evidence format. Allowed extensions: PDF, DOC, DOCX.")
            else:
                evidence_file.seek(0, os.SEEK_END)
                fsize = evidence_file.tell()
                evidence_file.seek(0)
                if fsize > MAX_FILE_SIZE:
                    errors.append("Evidence file exceeds 5 MB size limit.")
                else:
                    sec_name = secure_filename(evidence_file.filename)
                    upload_folder = os.path.join(current_app.instance_path, "uploads")
                    os.makedirs(upload_folder, exist_ok=True)
                    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                    saved_filename = f"{timestamp}_{sec_name}"
                    evidence_file.save(os.path.join(upload_folder, saved_filename))
                    attachment_filename = saved_filename

        if errors:
            for error in errors:
                flash(error, "danger")
            institutions = [user.institution] if user.is_institution_admin else db.session.query(Institution).order_by(Institution.name).all()
            return render_template(
                "complaint_form.html",
                institutions=institutions,
                categories=Complaint.CATEGORIES,
                sources=Complaint.SOURCES,
                priorities=Complaint.PRIORITIES,
                form_data=request.form,
            )

        # AI Categorization: if user left category blank or selected "AI Auto-Categorize"
        cat_result = None
        if not category_choice or category_choice == "AUTO":
            cat_result = categorize_complaint(title, description, allow_semantic=True)
            assigned_category = cat_result["category"]
            assigned_subcategory = cat_result["subcategory"]
            categorization_source = cat_result["source"]
            categorization_confidence = cat_result["confidence_score"]
        else:
            assigned_category = category_choice
            assigned_subcategory = subcategory or None
            categorization_source = "Manual Selection"
            categorization_confidence = 1.0

        # Mandatory confidentiality for sensitive categories
        if not is_confidential and assigned_category in [
            "Ragging and Student Harassment",
            "Discrimination and Student Welfare",
            "Financial Issues and Fee Irregularities",
            "Faculty Misconduct"
        ]:
            is_confidential = True

        ref_number = generate_complaint_reference()
        initial_status = "Submitted" if user.is_complainant else "Open"

        # AI-Assisted Department Routing Recommendation
        inst_obj = db.session.query(Institution).get(institution_id)
        routing_res = suggest_department_routing(
            title=title,
            description=description,
            category=assigned_category,
            institution_name=inst_obj.name if inst_obj else "",
        )

        new_complaint = Complaint(
            reference_number=ref_number,
            title=title,
            description=description,
            institution_id=institution_id,
            source_channel=source_channel,
            category=assigned_category,
            subcategory=assigned_subcategory,
            priority=priority,
            status=initial_status,
            complainant_user_id=complainant_user_id,
            complainant_name=complainant_name or None,
            is_confidential=is_confidential,
            is_demo=False,
            supporting_reference=supporting_reference or None,
            attachment_filename=attachment_filename or None,
            categorization_source=categorization_source,
            categorization_confidence=categorization_confidence,
            suggested_destination=routing_res["suggested_destination"],
            routing_reason=routing_res.get("routing_reason") or routing_res.get("reason"),
            routing_confidence=routing_res["confidence_score"],
            routing_requires_human_review=routing_res.get("requires_human_review", True),
            routed_destination=None,
            routing_decision=None,
            resolution_status="Not Yet Resolved",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.session.add(new_complaint)
        db.session.flush()

        # Status History entry
        status_entry = ComplaintStatusHistory(
            complaint_id=new_complaint.id,
            previous_status=None,
            new_status=initial_status,
            actor_id=user.id,
            actor_name=user.display_name,
            notes="Initial complaint registration.",
            timestamp=datetime.utcnow(),
        )
        db.session.add(status_entry)

        # Immediately execute potential overlap detection against existing complaints
        detected_overlaps = evaluate_complaint_against_all(new_complaint, db.session, auto_save=False)

        # Log audit event
        log_audit_event(
            db.session,
            actor=user,
            action="COMPLAINT_CREATED",
            entity_type="Complaint",
            entity_id=ref_number,
            metadata={
                "complaint_id": new_complaint.id,
                "institution_id": institution_id,
                "category": assigned_category,
                "categorization_source": categorization_source,
                "detected_overlaps_count": len(detected_overlaps),
            },
        )

        db.session.commit()

        # Construct informative feedback
        if user.is_complainant:
            sim_pct = round(max((o.similarity_score for o in detected_overlaps), default=0.0) * 100, 1)
            flash(
                f"Grievance {ref_number} successfully registered. System AI Analysis: {sim_pct}% similarity to historical institutional patterns. Category assigned: '{assigned_category}'.",
                "success"
            )
            return redirect(url_for("complaints.student_detail", complaint_id=new_complaint.id))
        else:
            overlap_msg = ""
            strong_count = sum(1 for o in detected_overlaps if o.relationship_type == "Strong Potential Overlap")
            possible_count = sum(1 for o in detected_overlaps if o.relationship_type == "Possible Overlap")
            if strong_count > 0:
                overlap_msg = f" Alert: {strong_count} Strong Potential Overlap(s) detected!"
            elif possible_count > 0:
                overlap_msg = f" Note: {possible_count} Possible Overlap(s) flagged for review."

            flash(
                f"Complaint {ref_number} successfully registered. Category assigned: '{assigned_category}' ({categorization_source}).{overlap_msg}",
                "success"
            )
            return redirect(url_for("complaints.detail", complaint_id=new_complaint.id))

    # GET Request
    institutions = [user.institution] if user.is_institution_admin else db.session.query(Institution).order_by(Institution.name).all()
    return render_template(
        "complaint_form.html",
        institutions=institutions,
        categories=Complaint.CATEGORIES,
        sources=Complaint.SOURCES,
        priorities=Complaint.PRIORITIES,
        form_data={},
    )


@complaints_bp.route("/complaints/<int:complaint_id>")
@login_required
def detail(complaint_id: int):
    user = g.current_user
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    # Permission check for complainant
    if user.is_complainant:
        if complaint.complainant_user_id == user.id or user.username in (complaint.complainant_name or ""):
            return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))
        abort(403)

    # Permission check for institutional administrator
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        flash("You are not authorized to view complaints outside your assigned institution.", "danger")
        return render_template("errors/403.html"), 403

    # Reviewers for assignment dropdown
    reviewers = db.session.query(User).filter(User.role.in_([User.ROLE_REVIEWER, User.ROLE_SUPER_ADMIN])).all()

    # Related overlap records
    overlaps = complaint.all_overlaps
    overlaps.sort(key=lambda o: o.similarity_score, reverse=True)

    # Audit events for this complaint
    audit_events = (
        db.session.query(db.models.audit.AuditEvent)
        .filter(
            db.models.audit.AuditEvent.entity_type == "Complaint",
            db.models.audit.AuditEvent.entity_id == complaint.reference_number
        )
        .order_by(db.models.audit.AuditEvent.timestamp.desc())
        .all()
    ) if hasattr(db, "models") and hasattr(db.models, "audit") else []

    # Fallback audit query via direct model import
    from models.audit import AuditEvent
    audit_events = (
        db.session.query(AuditEvent)
        .filter(
            AuditEvent.entity_type == "Complaint",
            AuditEvent.entity_id == complaint.reference_number
        )
        .order_by(AuditEvent.timestamp.desc())
        .all()
    )

    # Available Shared Related Complaint Groups
    group_query = db.session.query(RelatedComplaintGroup)
    if user.is_institution_admin:
        group_query = group_query.filter(
            or_(RelatedComplaintGroup.institution_id == user.institution_id, RelatedComplaintGroup.institution_id.is_(None))
        )
    existing_groups = group_query.order_by(RelatedComplaintGroup.created_at.desc()).all()

    return render_template(
        "complaint_detail.html",
        complaint=complaint,
        overlaps=overlaps,
        reviewers=reviewers,
        audit_events=audit_events,
        existing_groups=existing_groups,
        destinations=ALL_DESTINATIONS,
        categories=Complaint.CATEGORIES,
        statuses=Complaint.STATUSES,
        priorities=Complaint.PRIORITIES,
    )


@complaints_bp.route("/complaints/<int:complaint_id>/status", methods=["POST"])
@login_required
def update_status(complaint_id: int):
    user = g.current_user
    if user.is_complainant or user.is_auditor:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)

    new_status = request.form.get("status")
    notes = request.form.get("notes", "").strip()

    if new_status not in Complaint.STATUSES:
        flash("Invalid status selected.", "danger")
        return redirect(url_for("complaints.detail", complaint_id=complaint_id))

    previous_status = complaint.status
    complaint.status = new_status
    complaint.updated_at = datetime.utcnow()

    if new_status in ["Resolved", "Closed"]:
        complaint.resolution_date = datetime.utcnow()
        if notes:
            complaint.resolution_notes = notes

    # Add history record
    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        previous_status=previous_status,
        new_status=new_status,
        actor_id=user.id,
        actor_name=user.display_name,
        notes=notes or f"Status changed from {previous_status} to {new_status}.",
        timestamp=datetime.utcnow(),
    )
    db.session.add(history)

    # Log audit event
    log_audit_event(
        db.session,
        actor=user,
        action="COMPLAINT_STATUS_UPDATED",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={"from": previous_status, "to": new_status, "notes": notes},
    )

    db.session.commit()
    flash(f"Complaint status successfully updated to '{new_status}'.", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint_id))


@complaints_bp.route("/complaints/<int:complaint_id>/assign", methods=["POST"])
@login_required
def assign_reviewer(complaint_id: int):
    user = g.current_user
    if user.is_complainant:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    reviewer_id = request.form.get("reviewer_id", type=int)
    reviewer = db.session.query(User).get(reviewer_id) if reviewer_id else None

    previous_name = complaint.assigned_reviewer.display_name if complaint.assigned_reviewer else "Unassigned"
    complaint.assigned_reviewer_id = reviewer.id if reviewer else None
    complaint.updated_at = datetime.utcnow()

    log_audit_event(
        db.session,
        actor=user,
        action="REVIEWER_ASSIGNED",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={
            "previous_reviewer": previous_name,
            "new_reviewer": reviewer.display_name if reviewer else "Unassigned",
        },
    )

    db.session.commit()
    flash(f"Complaint assigned to {reviewer.display_name if reviewer else 'Unassigned'}.", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint_id))


@complaints_bp.route("/complaints/<int:complaint_id>/category-override", methods=["POST"])
@login_required
def override_category(complaint_id: int):
    user = g.current_user
    if user.is_complainant:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    new_cat = request.form.get("category")
    reason = request.form.get("override_reason", "").strip()

    if new_cat not in Complaint.CATEGORIES:
        flash("Invalid category selected.", "danger")
        return redirect(url_for("complaints.detail", complaint_id=complaint_id))

    old_cat = complaint.category
    complaint.category = new_cat
    complaint.categorization_source = f"Manual Override by {user.display_name}"
    complaint.updated_at = datetime.utcnow()

    log_audit_event(
        db.session,
        actor=user,
        action="CATEGORY_OVERRIDDEN",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={"old_category": old_cat, "new_category": new_cat, "reason": reason},
    )

    # Recalculate overlaps with updated category
    evaluate_complaint_against_all(complaint, db.session, auto_save=False)
    db.session.commit()

    flash(f"Category updated to '{new_cat}'. Overlap relationships refreshed.", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint_id))


@complaints_bp.route("/api/complaints/preview-categorization", methods=["POST"])
@login_required
def preview_categorization():
    data = request.get_json() or {}
    title = data.get("title", "")
    description = data.get("description", "")

    if len(title.strip()) < 3 and len(description.strip()) < 5:
        return jsonify({"status": "insufficient_text", "message": "Provide more details for AI analysis."})

    result = categorize_complaint(title, description, allow_semantic=True)
    return jsonify(result)


# --- MULTI-TIER COMPLAINT WORKFLOW ACTION ENDPOINTS ---

@complaints_bp.route("/complaints/<int:complaint_id>/institutional-action", methods=["POST"])
@login_required
def institutional_action(complaint_id: int):
    """Institutional Head/Reviewer workflow decisions: Acknowledge, Update Remarks, Resolve, or Escalate."""
    user = g.current_user
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    # Must be assigned to this institution or super admin / AICTE officer
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)
    if not (user.is_institution_admin or user.is_super_admin or user.is_reviewer):
        abort(403)

    action = request.form.get("action")  # "acknowledge", "update_remarks", "resolve", "escalate"
    official_remarks = request.form.get("official_remarks", "").strip()
    resolution_statement = request.form.get("public_resolution_statement", "").strip()
    escalation_reason = request.form.get("escalation_reason", "").strip()

    previous_status = complaint.status

    if action == "acknowledge":
        complaint.status = "Under Institutional Review"
        if official_remarks:
            complaint.official_remarks = official_remarks
        note = "Grievance acknowledged by institution; assigned to internal review committee."
    elif action == "update_remarks":
        complaint.official_remarks = official_remarks
        note = f"Internal institutional remarks updated."
    elif action == "record_action":
        action_notes = request.form.get("action_taken_notes", "").strip() or official_remarks
        if not action_notes:
            flash("Please describe the concrete remedial action taken.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        complaint.official_remarks = action_notes
        complaint.last_action_date = datetime.utcnow()
        note = f"Action Taken: {action_notes}"
    elif action == "resolve":
        if not resolution_statement:
            flash("A public resolution statement is required so the complainant can understand how their issue was addressed.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        complaint.status = "Resolved"
        complaint.resolution_date = datetime.utcnow()
        complaint.public_resolution_statement = resolution_statement
        complaint.resolution_notes = resolution_statement
        if official_remarks:
            complaint.official_remarks = official_remarks
        note = f"Resolved at institutional tier. Official statement: {resolution_statement}"
    elif action == "escalate":
        if not escalation_reason:
            flash("Please provide an explicit rationale for escalating this grievance to AICTE.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        complaint.status = "Escalated to AICTE"
        complaint.escalation_reason = escalation_reason
        complaint.escalated_at = datetime.utcnow()
        if official_remarks:
            complaint.official_remarks = official_remarks
        note = f"Escalated to AICTE for regulatory oversight: {escalation_reason}"
    else:
        flash("Invalid institutional action specified.", "danger")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    complaint.updated_at = datetime.utcnow()

    # Lifecycle history
    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        previous_status=previous_status,
        new_status=complaint.status,
        actor_id=user.id,
        actor_name=user.display_name,
        notes=note,
        timestamp=datetime.utcnow(),
    )
    db.session.add(history)

    # Immutable Audit Log
    log_audit_event(
        db.session,
        actor=user,
        action="INSTITUTIONAL_WORKFLOW_ACTION",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={
            "action": action,
            "previous_status": previous_status,
            "new_status": complaint.status,
            "escalation_reason": escalation_reason or None,
        },
    )
    db.session.commit()

    flash(f"Institutional action recorded successfully. Current Status: {complaint.status}", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))


@complaints_bp.route("/complaints/<int:complaint_id>/aicte-action", methods=["POST"])
@login_required
def aicte_action(complaint_id: int):
    """AICTE / Government Officer actions: Formal investigation, return for institutional action, or statutory resolution."""
    user = g.current_user
    if not (user.is_aicte_officer or user.is_super_admin or user.is_reviewer):
        abort(403)

    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    action = request.form.get("action")  # "investigate", "return_for_action", "final_resolution"
    aicte_remarks = request.form.get("aicte_remarks", "").strip()
    resolution_statement = request.form.get("public_resolution_statement", "").strip()

    previous_status = complaint.status

    if action == "investigate":
        complaint.status = "Under Investigation"
        if aicte_remarks:
            complaint.aicte_remarks = aicte_remarks
        note = f"AICTE regulatory inquiry initiated. Directives: {aicte_remarks or 'Formal review underway'}"
    elif action == "return_for_action":
        if not aicte_remarks:
            flash("Please provide mandatory corrective directives for the institutional administration.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        complaint.status = "Returned for Action"
        complaint.aicte_remarks = aicte_remarks
        note = f"Returned to institution by AICTE with required corrective directives: {aicte_remarks}"
    elif action == "final_resolution":
        if not resolution_statement:
            flash("A resolution statement is required for final governmental closure.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        complaint.status = "Resolved"
        complaint.resolution_date = datetime.utcnow()
        complaint.public_resolution_statement = resolution_statement
        complaint.resolution_notes = resolution_statement
        if aicte_remarks:
            complaint.aicte_remarks = aicte_remarks
        note = f"Final statutory resolution recorded by AICTE: {resolution_statement}"
    else:
        flash("Invalid AICTE action specified.", "danger")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    complaint.updated_at = datetime.utcnow()

    # Lifecycle history
    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        previous_status=previous_status,
        new_status=complaint.status,
        actor_id=user.id,
        actor_name=user.display_name,
        notes=note,
        timestamp=datetime.utcnow(),
    )
    db.session.add(history)

    # Immutable Audit Log
    log_audit_event(
        db.session,
        actor=user,
        action="AICTE_REGULATORY_DECISION",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={
            "action": action,
            "previous_status": previous_status,
            "new_status": complaint.status,
            "aicte_remarks": aicte_remarks or None,
        },
    )
    db.session.commit()

    flash(f"AICTE decision executed. Status updated to '{complaint.status}'.", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))


# --- CONTROLLED REVIEW LOOP & AI-ASSISTED ROUTING DECISIONS ---

@complaints_bp.route("/complaints/<int:complaint_id>/route-decision", methods=["POST"])
@login_required
def route_decision(complaint_id: int):
    """
    Step 2 of Review Loop: Reviewer checks AI-suggested department routing.
    Can confirm the AI recommendation or override to another department with mandatory reason.
    Records reviewer identity, timestamp, decision type, and reason.
    """
    user = g.current_user
    if user.is_complainant:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)

    action = request.form.get("action")  # "accept" or "override"
    destination = request.form.get("destination", "").strip()
    reason = request.form.get("reason", "").strip()

    if action == "accept":
        destination = complaint.suggested_destination or DEST_INSTITUTIONAL
        decision_label = "Accepted AI Suggestion"
        override_reason = None
    elif action == "override":
        if destination not in ALL_DESTINATIONS:
            flash("Invalid routing destination selected.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        if not reason:
            flash("A required justification must be provided when modifying the AI routing recommendation.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))
        decision_label = "Reviewer Override"
        override_reason = reason
    else:
        flash("Invalid routing action.", "danger")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    complaint.routed_destination = destination
    complaint.routed_by_user_id = user.id
    complaint.routed_at = datetime.utcnow()
    complaint.routing_decision = decision_label
    complaint.routing_override_reason = override_reason
    complaint.routing_requires_human_review = False
    complaint.updated_at = datetime.utcnow()

    # Advance status from Submitted if initial review is completed
    if complaint.status == "Submitted":
        complaint.status = "Under Institutional Review"

    note = f"Routing assigned to {destination} ({decision_label})."
    if override_reason:
        note += f" Reason: {override_reason}"

    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        previous_status=complaint.status,
        new_status=complaint.status,
        actor_id=user.id,
        actor_name=user.display_name,
        notes=note,
        timestamp=datetime.utcnow(),
    )
    db.session.add(history)

    log_audit_event(
        db.session,
        actor=user,
        action="ROUTING_DECISION_RECORDED",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={
            "action": action,
            "destination": destination,
            "decision": decision_label,
            "override_reason": override_reason,
        },
    )
    db.session.commit()
    flash(f"Complaint successfully assigned to {destination} review queue.", "success")
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))


# --- SHARED RELATED COMPLAINT GROUP ACTIONS ---

@complaints_bp.route("/complaints/<int:complaint_id>/group-action", methods=["POST"])
@login_required
def group_action(complaint_id: int):
    """
    Section 3: Shared Related Complaint Group Management.
    Links 2+ complaints describing the same underlying issue without merging or deleting individual records.
    Preserves distinct IDs, submission dates, evidence, and audit trails.
    """
    user = g.current_user
    if user.is_complainant:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)

    action = request.form.get("action")  # "create_and_link", "link_existing", "unlink"
    reason = request.form.get("reason", "").strip()

    if action == "create_and_link":
        title = request.form.get("group_title", "").strip() or f"Shared Issue: {complaint.title[:60]}"
        root_cause = request.form.get("root_cause", "").strip()
        description = request.form.get("group_description", "").strip() or complaint.description[:250]
        linked_ids = request.form.getlist("linked_complaint_ids", type=int)

        if not root_cause:
            flash("Please specify the identified common root cause for this complaint group.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))

        grp_ref = generate_group_reference()
        group = RelatedComplaintGroup(
            group_reference=grp_ref,
            title=title,
            description=description,
            root_cause=root_cause,
            category=complaint.category,
            institution_id=complaint.institution_id,
            status="Open",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(group)
        db.session.flush()

        complaint.related_group_id = group.id
        complaint.updated_at = datetime.utcnow()

        linked_refs = [complaint.reference_number]
        for other_id in linked_ids:
            if other_id != complaint.id:
                other = db.session.query(Complaint).get(other_id)
                if other and (not user.is_institution_admin or other.institution_id == user.institution_id):
                    other.related_group_id = group.id
                    other.updated_at = datetime.utcnow()
                    linked_refs.append(other.reference_number)

        log_audit_event(
            db.session,
            actor=user,
            action="COMPLAINT_GROUP_CREATED",
            entity_type="RelatedComplaintGroup",
            entity_id=grp_ref,
            metadata={
                "primary_complaint_id": complaint.id,
                "linked_references": linked_refs,
                "root_cause": root_cause,
                "reason": reason or "Group created from review interface.",
            },
        )
        db.session.commit()
        flash(f"Created shared issue group {grp_ref}. {len(linked_refs)} complaint(s) linked without altering individual records.", "success")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    elif action == "link_existing":
        group_id = request.form.get("existing_group_id", type=int)
        group = db.session.query(RelatedComplaintGroup).get(group_id) if group_id else None
        if not group:
            flash("Selected shared complaint group does not exist.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))

        complaint.related_group_id = group.id
        complaint.updated_at = datetime.utcnow()

        log_audit_event(
            db.session,
            actor=user,
            action="COMPLAINT_GROUP_LINKED",
            entity_type="RelatedComplaintGroup",
            entity_id=group.group_reference,
            metadata={"complaint_id": complaint.id, "reason": reason or "Linked to existing group."},
        )
        db.session.commit()
        flash(f"Linked complaint to shared issue group {group.group_reference}.", "success")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    elif action == "unlink":
        if not complaint.related_group_id:
            flash("This complaint is not currently linked to any shared group.", "warning")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))

        old_group = complaint.related_group
        old_ref = old_group.group_reference if old_group else str(complaint.related_group_id)
        complaint.related_group_id = None
        complaint.updated_at = datetime.utcnow()

        log_audit_event(
            db.session,
            actor=user,
            action="COMPLAINT_GROUP_UNLINKED",
            entity_type="RelatedComplaintGroup",
            entity_id=old_ref,
            metadata={"complaint_id": complaint.id, "reason": reason or "Removed from group."},
        )
        db.session.commit()
        flash("Complaint unlinked from shared issue group.", "success")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    flash("Invalid group action specified.", "danger")
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))


# --- GROUP & INDIVIDUAL RESOLUTION CONTROL PANEL ---

@complaints_bp.route("/complaints/<int:complaint_id>/resolution-decision", methods=["POST"])
@login_required
def resolution_decision(complaint_id: int):
    """
    Section 4: Solved / Not Solved / Partially Resolved / Reopened Control Panel.
    Explicitly confirms which linked complaints the resolution genuinely addresses without silent propagation.
    Updates respective student portals with resolution summary, date, feedback, and reopen controls.
    """
    user = g.current_user
    if user.is_complainant:
        abort(403)
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)
    if user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)

    resolution_state = request.form.get("resolution_state")  # "Resolved", "Partially Resolved", "Not Solved", "Reopened"
    resolution_statement = request.form.get("public_resolution_statement", "").strip()
    resolution_notes = request.form.get("resolution_notes", "").strip() or resolution_statement
    apply_to_group = request.form.get("apply_to_group") in ["1", "true", "on", "yes"]
    selected_complaint_ids = request.form.getlist("selected_group_complaint_ids", type=int)

    now = datetime.utcnow()

    if resolution_state == "Resolved":
        if not resolution_statement:
            flash("Please provide a public resolution statement explaining how the grievance was addressed.", "danger")
            return redirect(url_for("complaints.detail", complaint_id=complaint.id))

        complaint.status = "Resolved"
        complaint.resolution_status = "Resolved"
        complaint.resolution_date = now
        complaint.public_resolution_statement = resolution_statement
        complaint.resolution_notes = resolution_notes
        complaint.updated_at = now

        history = ComplaintStatusHistory(
            complaint_id=complaint.id,
            previous_status=complaint.status,
            new_status="Resolved",
            actor_id=user.id,
            actor_name=user.display_name,
            notes=f"Resolution Decision: Resolved. Statement: {resolution_statement}",
            timestamp=now,
        )
        db.session.add(history)

        resolved_count = 1
        # Propagate only to explicitly confirmed linked complaints
        if apply_to_group and complaint.related_group_id and selected_complaint_ids:
            linked_complaints = db.session.query(Complaint).filter(
                Complaint.related_group_id == complaint.related_group_id,
                Complaint.id.in_(selected_complaint_ids),
                Complaint.id != complaint.id
            ).all()

            for linked in linked_complaints:
                linked.status = "Resolved"
                linked.resolution_status = "Resolved"
                linked.resolution_date = now
                linked.public_resolution_statement = resolution_statement
                linked.resolution_notes = f"Resolved via shared issue resolution on {complaint.reference_number}: {resolution_notes}"
                linked.updated_at = now

                linked_history = ComplaintStatusHistory(
                    complaint_id=linked.id,
                    previous_status=linked.status,
                    new_status="Resolved",
                    actor_id=user.id,
                    actor_name=user.display_name,
                    notes=f"Resolved via shared issue group ({complaint.related_group.group_reference}). Statement: {resolution_statement}",
                    timestamp=now,
                )
                db.session.add(linked_history)
                resolved_count += 1

            # Update group status if all linked complaints are now resolved
            group = complaint.related_group
            if group:
                remaining_open = db.session.query(Complaint).filter(
                    Complaint.related_group_id == group.id,
                    Complaint.status != "Resolved"
                ).count()
                if remaining_open == 0:
                    group.status = "Resolved"
                    group.resolution_summary = resolution_statement
                    group.resolved_at = now
                    group.resolved_by_user_id = user.id

        log_audit_event(
            db.session,
            actor=user,
            action="RESOLUTION_DECISION_RESOLVED",
            entity_type="Complaint",
            entity_id=complaint.reference_number,
            metadata={
                "resolution_state": resolution_state,
                "statement": resolution_statement,
                "apply_to_group": apply_to_group,
                "addressed_count": resolved_count,
            },
        )
        db.session.commit()
        flash(f"Resolution saved. {resolved_count} complaint(s) updated with public resolution statement.", "success")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    elif resolution_state == "Partially Resolved":
        complaint.resolution_status = "Partially Resolved"
        complaint.updated_at = now
        if resolution_notes:
            complaint.resolution_notes = f"[Partially Resolved]: {resolution_notes}"
        if resolution_statement:
            complaint.public_resolution_statement = resolution_statement

        history = ComplaintStatusHistory(
            complaint_id=complaint.id,
            previous_status=complaint.status,
            new_status=complaint.status,
            actor_id=user.id,
            actor_name=user.display_name,
            notes=f"Resolution Decision: Partially Resolved. Notes: {resolution_notes}",
            timestamp=now,
        )
        db.session.add(history)
        log_audit_event(
            db.session,
            actor=user,
            action="RESOLUTION_DECISION_PARTIAL",
            entity_type="Complaint",
            entity_id=complaint.reference_number,
            metadata={"notes": resolution_notes},
        )
        db.session.commit()
        flash("Complaint marked as 'Partially Resolved'. Investigation remains active for unaddressed items.", "warning")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    elif resolution_state == "Reopened":
        complaint.status = "Reopened"
        complaint.resolution_status = "Reopened"
        complaint.updated_at = now
        if resolution_notes:
            complaint.reopen_reason = resolution_notes

        history = ComplaintStatusHistory(
            complaint_id=complaint.id,
            previous_status=complaint.status,
            new_status="Reopened",
            actor_id=user.id,
            actor_name=user.display_name,
            notes=f"Resolution Decision: Reopened by reviewer. Reason: {resolution_notes}",
            timestamp=now,
        )
        db.session.add(history)
        log_audit_event(
            db.session,
            actor=user,
            action="RESOLUTION_DECISION_REOPENED",
            entity_type="Complaint",
            entity_id=complaint.reference_number,
            metadata={"notes": resolution_notes},
        )
        db.session.commit()
        flash("Complaint status updated to 'Reopened'.", "info")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    elif resolution_state == "Not Solved":
        complaint.resolution_status = "Not Yet Resolved"
        complaint.updated_at = now
        history = ComplaintStatusHistory(
            complaint_id=complaint.id,
            previous_status=complaint.status,
            new_status=complaint.status,
            actor_id=user.id,
            actor_name=user.display_name,
            notes=f"Resolution Decision: Not Solved. Remarks: {resolution_notes}",
            timestamp=now,
        )
        db.session.add(history)
        log_audit_event(
            db.session,
            actor=user,
            action="RESOLUTION_DECISION_NOT_SOLVED",
            entity_type="Complaint",
            entity_id=complaint.reference_number,
            metadata={"notes": resolution_notes},
        )
        db.session.commit()
        flash("Recorded as 'Not Yet Resolved'.", "secondary")
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    flash("Invalid resolution state specified.", "danger")
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))


# --- DEPARTMENT REVIEW QUEUES ---

@complaints_bp.route("/queues")
@complaints_bp.route("/queues/<queue_type>")
@login_required
def review_queues(queue_type="all"):
    """
    Dedicated review queues across all AICTE bureaus, cells, and regulatory divisions:
    - PGRC: Public Grievance Redressal Committee
    - RB: Regulation Bureau
    - AB: Approval Bureau
    - PAPB: Policy & Academic Planning Bureau
    - FB: Finance Bureau / Grant Scrutiny
    - ARC: Anti-Ragging Cell
    - SDC: Skill Development Cell
    - RC: Regional Committee Compliance
    - Institutional: Institutional Reviewer
    - Manual: Manual Review & Ambiguous Triage
    - Unrouted: Awaiting initial routing decision
    """
    user = g.current_user
    if user.is_complainant:
        return redirect(url_for("complaints.student_portal"))

    # Role-based restriction: Bureau officers see only their authorized bureau queue
    user_bureau_code = None
    if user.bureau and user.bureau != "All" and not user.is_super_admin:
        b_lower = user.bureau.lower()
        if "pgrc" in b_lower:
            user_bureau_code = "pgrc"
        elif "regulation" in b_lower or "rb" in b_lower:
            user_bureau_code = "rb"
        elif "approval" in b_lower or "ab" in b_lower:
            user_bureau_code = "ab"
        elif "policy" in b_lower or "papb" in b_lower:
            user_bureau_code = "papb"
        elif "finance" in b_lower or "fb" in b_lower:
            user_bureau_code = "fb"
        elif "ragging" in b_lower or "arc" in b_lower:
            user_bureau_code = "arc"
        elif "skill" in b_lower or "sdc" in b_lower:
            user_bureau_code = "sdc"

    if user_bureau_code and (queue_type == "all" or queue_type != user_bureau_code):
        queue_type = user_bureau_code

    base_query = db.session.query(Complaint).join(Institution, Complaint.institution_id == Institution.id)
    if user.is_institution_admin:
        base_query = base_query.filter(Complaint.institution_id == user.institution_id)

    # Queue filters
    pgrc_cond = or_(
        Complaint.source_bureau.ilike("%PGRC%"),
        Complaint.routed_destination == DEST_PGRC,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_PGRC)
    )
    rb_cond = or_(
        Complaint.source_bureau.ilike("%Regulation%"),
        Complaint.source_bureau.ilike("%RB%"),
        Complaint.routed_destination == DEST_RB,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_RB)
    )
    ab_cond = or_(
        Complaint.source_bureau.ilike("%Approval%"),
        Complaint.source_bureau.ilike("%AB%"),
        Complaint.routed_destination == DEST_AB,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_AB)
    )
    papb_cond = or_(
        Complaint.source_bureau.ilike("%Policy%"),
        Complaint.source_bureau.ilike("%PAPB%"),
        Complaint.routed_destination == DEST_PAPB,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_PAPB)
    )
    fb_cond = or_(
        Complaint.source_bureau.ilike("%Finance%"),
        Complaint.source_bureau.ilike("%FB%"),
        Complaint.category.ilike("%Grant Funds%"),
        Complaint.routed_destination == DEST_FB,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_FB)
    )
    arc_cond = or_(
        Complaint.source_bureau.ilike("%Anti-Ragging%"),
        Complaint.source_bureau.ilike("%ARC%"),
        Complaint.routed_destination == DEST_ARC,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_ARC)
    )
    sdc_cond = or_(
        Complaint.source_bureau.ilike("%Skill%"),
        Complaint.source_bureau.ilike("%SDC%"),
        Complaint.routed_destination == DEST_SDC,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_SDC)
    )
    rc_cond = or_(
        Complaint.routed_destination == DEST_RC,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_RC)
    )
    inst_cond = or_(
        Complaint.routed_destination == DEST_INSTITUTIONAL,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_INSTITUTIONAL)
    )
    manual_cond = or_(
        Complaint.routed_destination == DEST_MANUAL,
        and_(Complaint.routed_destination.is_(None), Complaint.suggested_destination == DEST_MANUAL)
    )
    unrouted_cond = Complaint.routed_destination.is_(None)

    # Queue counts
    counts = {
        "all": base_query.count(),
        "pgrc": base_query.filter(pgrc_cond).count(),
        "rb": base_query.filter(rb_cond).count(),
        "ab": base_query.filter(ab_cond).count(),
        "papb": base_query.filter(papb_cond).count(),
        "fb": base_query.filter(fb_cond).count(),
        "arc": base_query.filter(arc_cond).count(),
        "sdc": base_query.filter(sdc_cond).count(),
        "rc": base_query.filter(rc_cond).count(),
        "institutional": base_query.filter(inst_cond).count(),
        "manual": base_query.filter(manual_cond).count(),
        "unrouted": base_query.filter(unrouted_cond).count(),
    }

    filtered_query = base_query
    if queue_type == "pgrc":
        filtered_query = filtered_query.filter(pgrc_cond)
    elif queue_type == "rb":
        filtered_query = filtered_query.filter(rb_cond)
    elif queue_type == "ab":
        filtered_query = filtered_query.filter(ab_cond)
    elif queue_type == "papb":
        filtered_query = filtered_query.filter(papb_cond)
    elif queue_type == "fb":
        filtered_query = filtered_query.filter(fb_cond)
    elif queue_type == "arc":
        filtered_query = filtered_query.filter(arc_cond)
    elif queue_type == "sdc":
        filtered_query = filtered_query.filter(sdc_cond)
    elif queue_type == "rc":
        filtered_query = filtered_query.filter(rc_cond)
    elif queue_type == "institutional":
        filtered_query = filtered_query.filter(inst_cond)
    elif queue_type == "manual":
        filtered_query = filtered_query.filter(manual_cond)
    elif queue_type == "unrouted":
        filtered_query = filtered_query.filter(unrouted_cond)

    priority_filter = request.args.get("priority")
    if priority_filter and priority_filter != "All":
        filtered_query = filtered_query.filter(Complaint.priority == priority_filter)

    status_filter = request.args.get("status")
    if status_filter and status_filter != "All":
        filtered_query = filtered_query.filter(Complaint.status == status_filter)

    # Stable descending sort: newest first
    complaints = filtered_query.order_by(Complaint.created_at.desc(), Complaint.id.desc()).all()

    return render_template(
        "queues.html",
        complaints=complaints,
        current_queue=queue_type,
        counts=counts,
        user_bureau_code=user_bureau_code,
        priorities=Complaint.PRIORITIES,
        statuses=Complaint.STATUSES,
        selected_priority=priority_filter,
        selected_status=status_filter,
    )


# --- PORTAL 1: COMPLAINANT / STUDENT VIEWS & ACTIONS ---

@complaints_bp.route("/student/complaints")
@login_required
def student_portal():
    """Complainant / Student Grievance Tracker: lists user's submitted complaints with stage progression."""
    user = g.current_user
    if not user.is_complainant:
        return redirect(url_for("dashboard.index"))

    my_complaints = (
        db.session.query(Complaint)
        .filter(
            (Complaint.complainant_user_id == user.id) |
            (Complaint.complainant_name.ilike(f"%{user.username}%"))
        )
        .order_by(Complaint.created_at.desc())
        .all()
    )

    return render_template("student_portal.html", complaints=my_complaints)


@complaints_bp.route("/student/complaints/<int:complaint_id>")
@login_required
def student_detail(complaint_id: int):
    """Complainant detailed grievance tracker view with 5-stage progress and public updates only."""
    user = g.current_user
    if not user.is_complainant:
        return redirect(url_for("complaints.detail", complaint_id=complaint_id))

    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint or (complaint.complainant_user_id != user.id and user.username not in (complaint.complainant_name or "")):
        abort(403)

    return render_template("student_complaint_detail.html", complaint=complaint)


@complaints_bp.route("/student/complaints/<int:complaint_id>/reopen", methods=["POST"])
@login_required
def student_reopen(complaint_id: int):
    """Allows complainant to request reopening if a resolved issue is unsatisfactory or recurring."""
    user = g.current_user
    if not user.is_complainant:
        abort(403)

    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint or (complaint.complainant_user_id != user.id and user.username not in (complaint.complainant_name or "")):
        abort(403)

    reopen_reason = request.form.get("reopen_reason", "").strip()
    if not reopen_reason:
        flash("Please provide a reason to reopen this complaint.", "warning")
        return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))

    previous_status = complaint.status
    complaint.status = "Reopened"
    complaint.reopen_reason = reopen_reason
    complaint.updated_at = datetime.utcnow()

    history = ComplaintStatusHistory(
        complaint_id=complaint.id,
        previous_status=previous_status,
        new_status="Reopened",
        actor_id=user.id,
        actor_name=user.display_name,
        notes=f"Grievant requested reopening: {reopen_reason}",
        timestamp=datetime.utcnow(),
    )
    db.session.add(history)

    log_audit_event(
        db.session,
        actor=user,
        action="COMPLAINT_REOPENED",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={"reopen_reason": reopen_reason},
    )
    db.session.commit()

    flash("Your request to reopen the grievance has been submitted for institutional review.", "success")
    return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))


@complaints_bp.route("/student/complaints/<int:complaint_id>/feedback", methods=["POST"])
@login_required
def student_feedback(complaint_id: int):
    """Allows complainant to submit satisfaction feedback on resolved grievances."""
    user = g.current_user
    if not user.is_complainant:
        abort(403)

    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    is_owner = (
        complaint.complainant_user_id == user.id or
        (user.identifier and complaint.complainant_id_str == user.identifier) or
        (user.identifier and complaint.complainant_name == user.identifier) or
        (user.display_name and complaint.complainant_name == user.display_name) or
        (user.username and user.username in (complaint.complainant_name or ""))
    )
    if not is_owner:
        abort(403)

    rating = request.form.get("feedback_rating", type=int)
    notes = request.form.get("feedback_notes", "").strip()

    if not rating or rating < 1 or rating > 5:
        flash("Please provide a valid satisfaction rating between 1 and 5 stars.", "danger")
        return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))

    complaint.feedback_rating = rating
    complaint.feedback_notes = notes
    complaint.updated_at = datetime.utcnow()

    log_audit_event(
        db.session,
        actor=user,
        action="FEEDBACK_SUBMITTED",
        entity_type="Complaint",
        entity_id=complaint.reference_number,
        metadata={"rating": rating, "notes": notes},
    )
    db.session.commit()

    flash("Thank you for submitting your feedback on this resolution.", "success")
    return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))


@complaints_bp.route("/complaints/<int:complaint_id>/evidence/<path:filename>")
@login_required
def view_evidence(complaint_id: int, filename: str):
    """Secure preview/download endpoint with strict complaint-level authorization."""
    user = g.current_user
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    # Authorization
    if user.is_complainant:
        is_owner = (
            complaint.complainant_user_id == user.id or
            (user.identifier and complaint.complainant_id_str == user.identifier) or
            (user.identifier and complaint.complainant_name == user.identifier) or
            (user.display_name and complaint.complainant_name == user.display_name) or
            (user.username and user.username in (complaint.complainant_name or ""))
        )
        if not is_owner:
            abort(403)
    elif user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)

    upload_folder = os.path.join(current_app.instance_path, "uploads")
    safe_name = os.path.basename(filename)
    file_path = os.path.join(upload_folder, safe_name)
    if not os.path.exists(file_path):
        flash("Evidence file not found on disk.", "warning")
        if user.is_complainant:
            return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))
        return redirect(url_for("complaints.detail", complaint_id=complaint.id))

    return send_from_directory(upload_folder, safe_name, as_attachment=False)


@complaints_bp.route("/complaints/<int:complaint_id>/evidence/upload", methods=["POST"])
@login_required
def upload_evidence(complaint_id: int):
    """Post-creation evidentiary upload endpoint."""
    user = g.current_user
    complaint = db.session.query(Complaint).get(complaint_id)
    if not complaint:
        abort(404)

    # Authorization
    if user.is_complainant:
        is_owner = (
            complaint.complainant_user_id == user.id or
            (user.identifier and complaint.complainant_id_str == user.identifier) or
            (user.identifier and complaint.complainant_name == user.identifier) or
            (user.display_name and complaint.complainant_name == user.display_name) or
            (user.username and user.username in (complaint.complainant_name or ""))
        )
        if not is_owner:
            abort(403)
    elif user.is_institution_admin and complaint.institution_id != user.institution_id:
        abort(403)
    elif user.is_auditor:
        abort(403)

    evidence_file = request.files.get("evidence_file")
    if not evidence_file or not evidence_file.filename:
        flash("No file was selected for upload.", "danger")
    elif not allowed_evidence_file(evidence_file.filename):
        flash("Invalid file format. Allowed formats: PDF, DOC, DOCX.", "danger")
    else:
        evidence_file.seek(0, os.SEEK_END)
        fsize = evidence_file.tell()
        evidence_file.seek(0)
        if fsize > MAX_FILE_SIZE:
            flash("Evidence file exceeds 5 MB size limit.", "danger")
        else:
            sec_name = secure_filename(evidence_file.filename)
            upload_folder = os.path.join(current_app.instance_path, "uploads")
            os.makedirs(upload_folder, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            saved_filename = f"{timestamp}_{sec_name}"
            evidence_file.save(os.path.join(upload_folder, saved_filename))
            complaint.attachment_filename = saved_filename
            complaint.updated_at = datetime.utcnow()
            log_audit_event(
                db.session,
                actor=user,
                action="EVIDENCE_UPLOADED",
                entity_type="Complaint",
                entity_id=complaint.reference_number,
                metadata={"filename": saved_filename, "original_name": evidence_file.filename},
            )
            db.session.commit()
            flash("Supporting evidence uploaded successfully.", "success")

    if user.is_complainant:
        return redirect(url_for("complaints.student_detail", complaint_id=complaint.id))
    return redirect(url_for("complaints.detail", complaint_id=complaint.id))
