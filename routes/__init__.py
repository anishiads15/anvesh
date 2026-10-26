from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.complaints import complaints_bp
from routes.overlaps import overlaps_bp
from routes.institutions import institutions_bp
from routes.reports import reports_bp
from routes.settings import settings_bp

__all__ = [
    "auth_bp",
    "dashboard_bp",
    "complaints_bp",
    "overlaps_bp",
    "institutions_bp",
    "reports_bp",
    "settings_bp",
]
