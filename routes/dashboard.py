from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, redirect, url_for
from extensions import db
from models.institution import Institution
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from routes.auth import login_required, get_current_user
from services.analytics import get_dashboard_metrics, get_overlap_trends

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def root():
    user = g.get("current_user")
    if not user:
        return redirect(url_for("auth.login"))
    if user.is_complainant:
        return redirect(url_for("complaints.student_portal"))
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/dashboard")
@login_required
def index():
    user = g.current_user
    if user.is_complainant:
        return redirect(url_for("complaints.student_portal"))

    # Determine filter constraints based on user role
    inst_filter_id = request.args.get("institution_id", type=int)
    if user.is_institution_admin:
        inst_filter_id = user.institution_id

    cat_filter = request.args.get("category", type=str)
    if cat_filter == "All" or not cat_filter:
        cat_filter = None

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else None
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else None

    metrics = get_dashboard_metrics(
        db.session,
        institution_id=inst_filter_id,
        category=cat_filter,
        start_date=start_date,
        end_date=end_date,
    )
    overlap_trends = get_overlap_trends(db.session, institution_id=inst_filter_id)

    # Recent complaints query
    c_query = db.session.query(Complaint)
    if inst_filter_id:
        c_query = c_query.filter(Complaint.institution_id == inst_filter_id)
    recent_complaints = c_query.order_by(Complaint.created_at.desc()).limit(6).all()

    # Pending overlap alerts query
    o_query = db.session.query(OverlapRelationship).filter(OverlapRelationship.review_status == "Pending Review")
    if inst_filter_id:
        c_ids = [c.id for c in c_query.all()]
        o_query = o_query.filter(
            (OverlapRelationship.first_complaint_id.in_(c_ids)) |
            (OverlapRelationship.second_complaint_id.in_(c_ids))
        )
    pending_overlap_alerts = o_query.order_by(OverlapRelationship.similarity_score.desc()).limit(5).all()

    # All institutions for filter dropdown (if super admin or reviewer)
    institutions = []
    if not user.is_institution_admin:
        institutions = db.session.query(Institution).order_by(Institution.name).all()

    return render_template(
        "dashboard.html",
        metrics=metrics,
        recent_complaints=recent_complaints,
        pending_overlap_alerts=pending_overlap_alerts,
        institutions=institutions,
        selected_institution=inst_filter_id,
        selected_category=cat_filter,
        start_date=start_date_str,
        end_date=end_date_str,
        categories=Complaint.CATEGORIES,
        overlap_trends=overlap_trends,
    )


@dashboard_bp.route("/api/dashboard/metrics")
@login_required
def api_metrics():
    user = g.current_user
    if user.is_complainant:
        return jsonify({"error": "Forbidden"}), 403
    inst_id = request.args.get("institution_id", type=int)
    if user.is_institution_admin:
        inst_id = user.institution_id

    cat = request.args.get("category", type=str)
    if cat == "All":
        cat = None

    metrics = get_dashboard_metrics(db.session, institution_id=inst_id, category=cat)
    return jsonify(metrics)
