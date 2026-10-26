from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, jsonify
from extensions import db
from models.institution import Institution
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from routes.auth import login_required
from services.audit_service import log_audit_event
from services.overlap_detection import evaluate_complaint_against_all

overlaps_bp = Blueprint("overlaps", __name__)


@overlaps_bp.route("/overlaps")
@login_required
def index():
    user = g.current_user
    if user.is_complainant or user.is_institution_admin or user.is_auditor:
        return render_template("errors/403.html"), 403

    query = (
        db.session.query(OverlapRelationship)
        .join(Complaint, OverlapRelationship.first_complaint_id == Complaint.id)
    )

    # Institution admin role restriction
    if user.is_institution_admin:
        query = query.filter(
            (Complaint.institution_id == user.institution_id) |
            (OverlapRelationship.second_complaint.has(institution_id=user.institution_id))
        )

    # Filters
    status_filter = request.args.get("status", "Pending Review")
    if status_filter != "All" and status_filter:
        query = query.filter(OverlapRelationship.review_status == status_filter)

    strength_filter = request.args.get("strength")
    if strength_filter and strength_filter != "All":
        query = query.filter(OverlapRelationship.relationship_type == strength_filter)

    inst_filter = request.args.get("institution_id", type=int)
    if inst_filter and not user.is_institution_admin:
        query = query.filter(
            (Complaint.institution_id == inst_filter) |
            (OverlapRelationship.second_complaint.has(institution_id=inst_filter))
        )

    # Sort by similarity score descending
    overlaps = query.order_by(OverlapRelationship.similarity_score.desc()).all()

    # Pre-fetch counts for status tabs
    total_pending = db.session.query(OverlapRelationship).filter_by(review_status="Pending Review").count()
    total_confirmed = db.session.query(OverlapRelationship).filter_by(review_status="Confirmed Related").count()
    total_rejected = db.session.query(OverlapRelationship).filter_by(review_status="Rejected Not Related").count()

    institutions = []
    if not user.is_institution_admin:
        institutions = db.session.query(Institution).order_by(Institution.name).all()

    return render_template(
        "overlaps.html",
        overlaps=overlaps,
        institutions=institutions,
        selected_status=status_filter,
        selected_strength=strength_filter,
        selected_institution=inst_filter,
        total_pending=total_pending,
        total_confirmed=total_confirmed,
        total_rejected=total_rejected,
    )


@overlaps_bp.route("/overlaps/<int:overlap_id>/review", methods=["POST"])
@login_required
def review_action(overlap_id: int):
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403
    overlap = db.session.query(OverlapRelationship).get(overlap_id)
    if not overlap:
        abort(404)

    # Role check
    if user.is_institution_admin:
        if (overlap.first_complaint.institution_id != user.institution_id and
            overlap.second_complaint.institution_id != user.institution_id):
            abort(403)

    action = request.form.get("action")  # "confirm", "reject", "reset"
    notes = request.form.get("review_notes", "").strip()

    previous_status = overlap.review_status

    if action == "confirm":
        overlap.review_status = "Confirmed Related"
        overlap.relationship_type = "Human-Confirmed Related"
        overlap.reviewer_id = user.id
        overlap.review_notes = notes
        overlap.reviewed_at = datetime.utcnow()
        feedback_msg = f"Complaints #{overlap.first_complaint_id} and #{overlap.second_complaint_id} confirmed as related by human reviewer."
    elif action == "reject":
        overlap.review_status = "Rejected Not Related"
        overlap.relationship_type = "Human-Confirmed Not Related"
        overlap.reviewer_id = user.id
        overlap.review_notes = notes
        overlap.reviewed_at = datetime.utcnow()
        feedback_msg = f"Complaints #{overlap.first_complaint_id} and #{overlap.second_complaint_id} marked as NOT related."
    elif action == "reset":
        overlap.review_status = "Pending Review"
        # Reset relationship type to algorithmic suggestion based on score
        overlap.relationship_type = "Strong Potential Overlap" if overlap.similarity_score >= 0.80 else "Possible Overlap"
        overlap.reviewer_id = None
        overlap.review_notes = None
        overlap.reviewed_at = None
        feedback_msg = f"Overlap relationship reset to Pending Review."
    else:
        flash("Invalid review action.", "danger")
        return redirect(url_for("overlaps.index"))

    log_audit_event(
        db.session,
        actor=user,
        action="OVERLAP_REVIEWED",
        entity_type="OverlapRelationship",
        entity_id=str(overlap.id),
        metadata={
            "first_complaint": overlap.first_complaint.reference_number,
            "second_complaint": overlap.second_complaint.reference_number,
            "previous_status": previous_status,
            "new_status": overlap.review_status,
            "action": action,
            "notes": notes,
        },
    )

    db.session.commit()
    flash(feedback_msg, "success")

    # Redirect back to referring page or overlaps queue
    return redirect(request.referrer or url_for("overlaps.index"))


@overlaps_bp.route("/overlaps/recalculate", methods=["POST"])
@login_required
def recalculate():
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403
    if not (user.is_super_admin or user.is_reviewer):
        abort(403)

    all_complaints = db.session.query(Complaint).all()
    count = 0
    for complaint in all_complaints:
        evaluate_complaint_against_all(complaint, db.session, auto_save=False)
        count += 1

    log_audit_event(
        db.session,
        actor=user,
        action="OVERLAPS_RECALCULATED",
        entity_type="OverlapRelationship",
        entity_id="ALL",
        metadata={"complaints_evaluated": count},
    )

    db.session.commit()
    flash(f"Recalculation complete across {count} complaints. Review queue refreshed.", "success")
    return redirect(url_for("overlaps.index"))
