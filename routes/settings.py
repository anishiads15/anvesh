import os
from flask import Blueprint, render_template, request, g, flash, redirect, url_for, current_app
from extensions import db
from models.audit import AuditEvent
from models.user import User
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from models.institution import Institution
from routes.auth import login_required, role_required
from services.categorization import _get_transformer_model

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/audit-log")
@settings_bp.route("/settings/audit-log")
@login_required
@role_required(User.ROLE_AICTE_OFFICER, User.ROLE_SUPER_ADMIN, User.ROLE_REVIEWER, User.ROLE_AUDITOR)
def audit_log():
    query = db.session.query(AuditEvent)

    action_filter = request.args.get("action")
    if action_filter and action_filter != "All":
        query = query.filter(AuditEvent.action == action_filter)

    entity_filter = request.args.get("entity_type")
    if entity_filter and entity_filter != "All":
        query = query.filter(AuditEvent.entity_type == entity_filter)

    actor_search = request.args.get("actor", "").strip()
    if actor_search:
        query = query.filter(AuditEvent.actor_name.ilike(f"%{actor_search}%"))

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = 20
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    events = query.order_by(AuditEvent.timestamp.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Distinct actions and entity types for filter dropdowns
    actions = [a[0] for a in db.session.query(AuditEvent.action).distinct().all()]
    entity_types = [e[0] for e in db.session.query(AuditEvent.entity_type).distinct().all()]

    return render_template(
        "audit_log.html",
        events=events,
        actions=actions,
        entity_types=entity_types,
        selected_action=action_filter,
        selected_entity=entity_filter,
        actor_search=actor_search,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


@settings_bp.route("/settings")
@login_required
def settings():
    user = g.current_user
    if user.is_complainant:
        return redirect(url_for("complaints.student_portal"))

    # Inspect AI Model state
    transformer = _get_transformer_model()
    ai_status = {
        "engine": "Sentence Transformers (all-MiniLM-L6-v2)" if transformer else "TF-IDF + N-Gram Cosine Similarity Fallback Engine",
        "is_transformer_active": transformer is not None,
        "model_name": current_app.config.get("AI_MODEL_NAME", "all-MiniLM-L6-v2"),
        "strong_threshold": current_app.config.get("OVERLAP_STRONG_THRESHOLD", 0.80),
        "possible_threshold": current_app.config.get("OVERLAP_POSSIBLE_THRESHOLD", 0.50),
        "scoring_weights": {
            "Semantic Text Similarity": "55%",
            "Shared Issue Keywords": "20%",
            "Category Compatibility": "15%",
            "Contextual Similarity": "10%",
        },
    }

    # System statistics derived directly from database queries without mutations
    total_complaints = db.session.query(Complaint).count()
    total_institutions = db.session.query(Institution).count()
    unique_stored_overlaps = db.session.query(OverlapRelationship).count()
    total_audit_events = db.session.query(AuditEvent).count()
    total_users = db.session.query(User).count()
    
    # Overlap pipeline diagnostic distributions
    strong_overlaps = db.session.query(OverlapRelationship).filter(OverlapRelationship.similarity_score >= 0.80).count()
    possible_overlaps = db.session.query(OverlapRelationship).filter(
        OverlapRelationship.similarity_score >= 0.50,
        OverlapRelationship.similarity_score < 0.80
    ).count()

    # Total pair evaluations tracked or combinatorially evaluated
    # Total unique pairwise evaluations across complaint catalog
    evaluations_count = (total_complaints * (total_complaints - 1)) // 2 if total_complaints > 1 else 0

    stats = {
        "total_complaints": total_complaints,
        "total_institutions": total_institutions,
        "total_overlaps": unique_stored_overlaps,
        "unique_stored_overlaps": unique_stored_overlaps,
        "total_evaluations": evaluations_count,
        "strong_overlaps": strong_overlaps,
        "possible_overlaps": possible_overlaps,
        "total_audit_events": total_audit_events,
        "total_users": total_users,
        "database_uri": current_app.config.get("SQLALCHEMY_DATABASE_URI"),
    }

    return render_template(
        "settings.html",
        ai_status=ai_status,
        stats=stats,
        user=user,
    )
