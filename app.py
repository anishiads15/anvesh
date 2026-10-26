import os
import logging
from flask import Flask, render_template, g, session, send_file
from config import Config
from extensions import db
from models.user import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aicte-portal")


def create_app(config_class=Config):
    """Application factory for the AICTE Integrated Complaint Monitoring Portal."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)

    with app.app_context():
        try:
            db.create_all()
            from scripts.seed_demo_data import ensure_schema_updated
            ensure_schema_updated()
        except Exception as e:
            logger.warning(f"Database schema initialization notice: {e}")

    # Inject global user into template contexts
    @app.before_request
    def load_authenticated_user():
        g.current_user = None
        user_id = session.get("user_id")
        if user_id:
            try:
                g.current_user = db.session.query(User).filter_by(id=user_id, is_active=True).first()
            except Exception:
                g.current_user = None

    @app.context_processor
    def inject_context():
        unread_notifications_count = 0
        user = g.get("current_user")
        if user:
            try:
                from models.notification import Notification
                from models.complaint import Complaint
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
                unread_notifications_count = query.count()
            except Exception:
                unread_notifications_count = 0
        return {
            "current_user": g.get("current_user"),
            "unread_notifications_count": unread_notifications_count,
        }

    # Register Blueprints
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.complaints import complaints_bp
    from routes.overlaps import overlaps_bp
    from routes.institutions import institutions_bp
    from routes.reports import reports_bp
    from routes.settings import settings_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(overlaps_bp)
    app.register_blueprint(institutions_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)

    @app.template_filter("format_datetime")
    def format_datetime_filter(dt, fmt="%d %b %Y, %H:%M UTC"):
        if not dt:
            return ""
        if isinstance(dt, str):
            from datetime import datetime as dt_cls
            for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                try:
                    dt = dt_cls.strptime(dt, f)
                    break
                except ValueError:
                    pass
        if hasattr(dt, "strftime"):
            return dt.strftime(fmt)
        return str(dt)

    @app.route("/download-zip")
    def download_zip():
        """Direct project source code archive download is strictly restricted."""
        from flask import abort
        abort(403)

    # Error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def internal_server_error(e):
        logger.error(f"Internal server error encountered: {e}")
        return render_template("errors/500.html"), 500

    # CLI commands
    @app.cli.command("init-db")
    def init_db_command():
        """Creates database schema tables."""
        db.create_all()
        logger.info("Database tables successfully created.")

    @app.cli.command("seed-data")
    def seed_data_command():
        """Seeds realistic demonstration institutions, complaints, overlaps, and users."""
        from scripts.seed_demo_data import seed_database
        seed_database()

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
