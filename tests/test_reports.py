import pytest
from datetime import datetime, timedelta
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from services.analytics import get_dashboard_metrics
from routes.reports import sanitize_csv_cell


def test_dashboard_metrics_accuracy(db_session, sample_institution):
    """Test dashboard metrics reflect accurate counts live from the database."""
    now = datetime.utcnow()
    c_open = Complaint(
        reference_number="AICTE-METRIC-1",
        title="Open complaint",
        description="Description for open complaint.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
        created_at=now,
    )
    c_review = Complaint(
        reference_number="AICTE-METRIC-2",
        title="Under review complaint",
        description="Description for under review complaint.",
        institution_id=sample_institution.id,
        category="Laboratory and equipment",
        status="Under Review",
        created_at=now - timedelta(days=5),
    )
    c_resolved = Complaint(
        reference_number="AICTE-METRIC-3",
        title="Resolved complaint",
        description="Description for resolved complaint.",
        institution_id=sample_institution.id,
        category="Academic quality",
        status="Resolved",
        created_at=now - timedelta(days=20),
        resolution_date=now - timedelta(days=10),
    )
    c_overdue = Complaint(
        reference_number="AICTE-METRIC-4",
        title="Overdue complaint",
        description="Description for overdue complaint.",
        institution_id=sample_institution.id,
        category="Student facilities",
        status="Open",
        created_at=now - timedelta(days=45),  # > 30 days
    )
    db_session.add_all([c_open, c_review, c_resolved, c_overdue])
    db_session.commit()

    metrics = get_dashboard_metrics(db_session)
    assert metrics["total_complaints"] == 4
    assert metrics["open_complaints"] == 2
    assert metrics["under_review_complaints"] == 1
    assert metrics["resolved_complaints"] == 1
    assert metrics["overdue_complaints"] == 1
    assert metrics["status_distribution"]["Open"] == 2
    assert metrics["status_distribution"]["Resolved"] == 1


def test_csv_formula_sanitization():
    """Test dangerous spreadsheet formula characters are neutralized with leading quote."""
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
    assert sanitize_csv_cell("-5+2") == "'-5+2"
    assert sanitize_csv_cell("@SUM(1,2)") == "'@SUM(1,2)"
    assert sanitize_csv_cell("Standard Title") == "Standard Title"
    assert sanitize_csv_cell(None) == ""


def test_csv_export_endpoint(client, super_admin_user, sample_institution, db_session):
    """Test CSV export requires authentication, sets appropriate headers, and returns CSV content."""
    # Without auth
    resp = client.get("/reports/export/complaints.csv")
    assert resp.status_code == 302  # Redirects to login

    # Authenticate
    client.post("/login", data={"username": "admin_test", "password": "AdminPass123"})

    c = Complaint(
        reference_number="AICTE-EXPORT-001",
        title="=DANGEROUS_FORMULA_INJECTION",
        description="Valid description text.",
        institution_id=sample_institution.id,
        category="Infrastructure",
        status="Open",
    )
    db_session.add(c)
    db_session.commit()

    resp = client.get("/reports/export/complaints.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment; filename=" in resp.headers.get("Content-Disposition", "")
    data = resp.data.decode("utf-8")
    assert "Reference Number,Title,Institution Name" in data
    # Formula must be escaped with single quote
    assert "'=DANGEROUS_FORMULA_INJECTION" in data
