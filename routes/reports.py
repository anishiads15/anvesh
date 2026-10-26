import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, Response, g, abort
from extensions import db
from models.institution import Institution
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from models.user import User
from routes.auth import login_required
from services.analytics import (
    get_dashboard_metrics,
    get_overlap_review_analytics,
    get_overlap_trends,
    get_overlap_network_graph,
    get_institution_overlap_comparison,
    get_category_overlap_analysis,
    get_recurrence_analysis,
)
from services.audit_service import log_audit_event

reports_bp = Blueprint("reports", __name__)


def sanitize_csv_cell(value) -> str:
    """Sanitizes text fields to prevent CSV formula injection in spreadsheet applications."""
    if value is None:
        return ""
    text = str(value)
    # Check for dangerous initial characters in Excel/Calc
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


@reports_bp.route("/reports")
@login_required
def index():
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403

    inst_id = request.args.get("institution_id", type=int)
    if user.is_institution_admin:
        inst_id = user.institution_id

    metrics = get_dashboard_metrics(db.session, institution_id=inst_id)
    overlap_stats = get_overlap_review_analytics(db.session)
    overlap_trends = get_overlap_trends(db.session, institution_id=inst_id)
    network_graph = get_overlap_network_graph(db.session, institution_id=inst_id)
    inst_comparison = get_institution_overlap_comparison(db.session)
    category_overlaps = get_category_overlap_analysis(db.session, institution_id=inst_id)
    recurrence_analysis = get_recurrence_analysis(db.session, institution_id=inst_id)

    # Reviewer workload analysis
    reviewers = db.session.query(User).filter(User.role.in_([User.ROLE_REVIEWER, User.ROLE_SUPER_ADMIN])).all()
    reviewer_workload = []
    for r in reviewers:
        assigned_c = db.session.query(Complaint).filter(Complaint.assigned_reviewer_id == r.id).count()
        reviewed_o = db.session.query(OverlapRelationship).filter(OverlapRelationship.reviewer_id == r.id).count()
        reviewer_workload.append({
            "name": r.display_name,
            "role": r.role_title(),
            "assigned_complaints": assigned_c,
            "reviewed_overlaps": reviewed_o,
        })

    institutions = []
    if not user.is_institution_admin:
        institutions = db.session.query(Institution).order_by(Institution.name).all()

    return render_template(
        "analytics.html",
        metrics=metrics,
        overlap_stats=overlap_stats,
        overlap_trends=overlap_trends,
        network_graph=network_graph,
        inst_comparison=inst_comparison,
        category_overlaps=category_overlaps,
        recurrence_analysis=recurrence_analysis,
        reviewer_workload=reviewer_workload,
        institutions=institutions,
        selected_institution=inst_id,
    )


@reports_bp.route("/reports/export/complaints.csv")
@login_required
def export_complaints_csv():
    user = g.current_user
    if not user.is_super_admin:
        return render_template("errors/403.html"), 403
    query = db.session.query(Complaint)

    if user.is_institution_admin:
        query = query.filter(Complaint.institution_id == user.institution_id)
    elif request.args.get("institution_id", type=int):
        query = query.filter(Complaint.institution_id == request.args.get("institution_id", type=int))

    complaints = query.order_by(Complaint.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "Reference Number",
        "Title",
        "Institution Name",
        "Institution Code",
        "Category",
        "Subcategory",
        "Priority",
        "Status",
        "Source Channel",
        "Assigned Reviewer",
        "Categorization Source",
        "Categorization Confidence",
        "Created At",
        "Resolution Date",
    ])

    for c in complaints:
        writer.writerow([
            sanitize_csv_cell(c.reference_number),
            sanitize_csv_cell(c.title),
            sanitize_csv_cell(c.institution.name if c.institution else ""),
            sanitize_csv_cell(c.institution.code if c.institution else ""),
            sanitize_csv_cell(c.category),
            sanitize_csv_cell(c.subcategory or ""),
            sanitize_csv_cell(c.priority),
            sanitize_csv_cell(c.status),
            sanitize_csv_cell(c.source_channel),
            sanitize_csv_cell(c.assigned_reviewer.display_name if c.assigned_reviewer else "Unassigned"),
            sanitize_csv_cell(c.categorization_source),
            sanitize_csv_cell(round(c.categorization_confidence, 2) if c.categorization_confidence else ""),
            sanitize_csv_cell(c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else ""),
            sanitize_csv_cell(c.resolution_date.strftime("%Y-%m-%d %H:%M:%S") if c.resolution_date else ""),
        ])

    log_audit_event(
        db.session,
        actor=user,
        action="REPORT_EXPORTED",
        entity_type="Report",
        entity_id="complaints.csv",
        metadata={"record_count": len(complaints)},
    )
    db.session.commit()

    filename = f"aicte_complaints_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@reports_bp.route("/reports/export/overlaps.csv")
@login_required
def export_overlaps_csv():
    user = g.current_user
    if user.is_complainant:
        return render_template("errors/403.html"), 403
    query = db.session.query(OverlapRelationship)

    if user.is_institution_admin:
        query = query.filter(
            (OverlapRelationship.first_complaint.has(institution_id=user.institution_id)) |
            (OverlapRelationship.second_complaint.has(institution_id=user.institution_id))
        )

    overlaps = query.order_by(OverlapRelationship.similarity_score.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "Overlap ID",
        "First Complaint Ref",
        "First Complaint Title",
        "First Institution",
        "Second Complaint Ref",
        "Second Complaint Title",
        "Second Institution",
        "Composite Similarity Score",
        "Semantic Score",
        "Keyword Score",
        "Category Score",
        "Context Score",
        "Relationship Strength",
        "Review Status",
        "Algorithm Version",
        "Reviewer Name",
        "Review Notes",
        "Created At",
        "Reviewed At",
    ])

    for o in overlaps:
        writer.writerow([
            sanitize_csv_cell(o.id),
            sanitize_csv_cell(o.first_complaint.reference_number if o.first_complaint else ""),
            sanitize_csv_cell(o.first_complaint.title if o.first_complaint else ""),
            sanitize_csv_cell(o.first_complaint.institution.name if o.first_complaint and o.first_complaint.institution else ""),
            sanitize_csv_cell(o.second_complaint.reference_number if o.second_complaint else ""),
            sanitize_csv_cell(o.second_complaint.title if o.second_complaint else ""),
            sanitize_csv_cell(o.second_complaint.institution.name if o.second_complaint and o.second_complaint.institution else ""),
            sanitize_csv_cell(round(o.similarity_score, 4)),
            sanitize_csv_cell(round(o.semantic_score, 4)),
            sanitize_csv_cell(round(o.keyword_score, 4)),
            sanitize_csv_cell(round(o.category_score, 4)),
            sanitize_csv_cell(round(o.context_score, 4)),
            sanitize_csv_cell(o.relationship_type),
            sanitize_csv_cell(o.review_status),
            sanitize_csv_cell(o.algorithm_version),
            sanitize_csv_cell(o.reviewer.display_name if o.reviewer else "Pending Review"),
            sanitize_csv_cell(o.review_notes or ""),
            sanitize_csv_cell(o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""),
            sanitize_csv_cell(o.reviewed_at.strftime("%Y-%m-%d %H:%M:%S") if o.reviewed_at else ""),
        ])

    log_audit_event(
        db.session,
        actor=user,
        action="REPORT_EXPORTED",
        entity_type="Report",
        entity_id="overlaps.csv",
        metadata={"record_count": len(overlaps)},
    )
    db.session.commit()

    filename = f"aicte_overlaps_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
