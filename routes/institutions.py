from flask import Blueprint, render_template, request, g, abort, redirect, url_for
from extensions import db
from models.institution import Institution
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from routes.auth import login_required

institutions_bp = Blueprint("institutions", __name__)


@institutions_bp.route("/institutions")
@login_required
def index():
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403
    if user.is_institution_admin:
        if user.institution_id:
            return redirect(url_for("institutions.detail", institution_id=user.institution_id))
        return render_template("errors/403.html"), 403
    query = db.session.query(Institution)

    # Search filter
    search = request.args.get("q", "").strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Institution.name.ilike(pattern)) |
            (Institution.code.ilike(pattern)) |
            (Institution.district.ilike(pattern)) |
            (Institution.state.ilike(pattern))
        )

    # State filter
    state_filter = request.args.get("state")
    if state_filter and state_filter != "All":
        query = query.filter(Institution.state == state_filter)

    type_filter = request.args.get("type")
    if type_filter and type_filter != "All":
        query = query.filter(Institution.institution_type == type_filter)

    institutions_list = query.order_by(Institution.name).all()

    # Calculate statistics for each institution
    enriched_institutions = []
    for inst in institutions_list:
        complaints = inst.complaints
        total_c = len(complaints)
        open_c = sum(1 for c in complaints if c.status not in ["Resolved", "Closed"])
        resolved_c = sum(1 for c in complaints if c.status in ["Resolved", "Closed"])
        overdue_c = sum(1 for c in complaints if getattr(c, "is_overdue", False))

        # Count pending overlaps involving this institution's complaints
        c_ids = [c.id for c in complaints]
        pending_overlaps = 0
        if c_ids:
            pending_overlaps = (
                db.session.query(OverlapRelationship)
                .filter(
                    OverlapRelationship.review_status == "Pending Review",
                    (OverlapRelationship.first_complaint_id.in_(c_ids)) |
                    (OverlapRelationship.second_complaint_id.in_(c_ids))
                )
                .count()
            )

        enriched_institutions.append({
            "institution": inst,
            "total_complaints": total_c,
            "open_complaints": open_c,
            "resolved_complaints": resolved_c,
            "overdue_complaints": overdue_c,
            "pending_overlaps": pending_overlaps,
            "recent_complaints": sorted(complaints, key=lambda c: (c.created_at or datetime.min), reverse=True)[:3],
        })

    # Available states and types for filter dropdowns
    all_states = sorted(list(set(i.state for i in db.session.query(Institution.state).all() if i.state)))
    all_types = sorted(list(set(i.institution_type for i in db.session.query(Institution.institution_type).all() if i.institution_type)))

    return render_template(
        "institutions.html",
        institutions=enriched_institutions,
        all_states=all_states,
        all_types=all_types,
        selected_state=state_filter,
        selected_type=type_filter,
        search_query=search,
    )


@institutions_bp.route("/institutions/<int:institution_id>")
@login_required
def detail(institution_id: int):
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403
    institution = db.session.query(Institution).get(institution_id)
    if not institution:
        abort(404)

    if user.is_institution_admin and user.institution_id != institution.id:
        abort(403)

    complaints = (
        db.session.query(Complaint)
        .filter(Complaint.institution_id == institution.id)
        .order_by(Complaint.created_at.desc(), Complaint.id.desc())
        .all()
    )

    c_ids = [c.id for c in complaints]
    overlaps = []
    if c_ids:
        overlaps = (
            db.session.query(OverlapRelationship)
            .filter(
                (OverlapRelationship.first_complaint_id.in_(c_ids)) |
                (OverlapRelationship.second_complaint_id.in_(c_ids))
            )
            .order_by(OverlapRelationship.similarity_score.desc())
            .all()
        )

    open_count = sum(1 for c in complaints if c.status not in ["Resolved", "Closed"])
    resolved_count = sum(1 for c in complaints if c.status in ["Resolved", "Closed"])
    overdue_count = sum(1 for c in complaints if getattr(c, "is_overdue", False))
    escalated_count = sum(1 for c in complaints if c.status == "Escalated to AICTE")
    pending_overlaps_count = sum(1 for o in overlaps if o.review_status == "Pending Review")

    return render_template(
        "institution_detail.html",
        institution=institution,
        complaints=complaints,
        overlaps=overlaps,
        open_count=open_count,
        resolved_count=resolved_count,
        overdue_count=overdue_count,
        escalated_count=escalated_count,
        pending_overlaps_count=pending_overlaps_count,
    )
