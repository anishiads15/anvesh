import pytest
from flask import session
from models.user import User
from models.audit import AuditEvent


def test_password_hashing(db_session):
    """Test that passwords are never stored in plaintext and hashing functions properly."""
    user = User(
        display_name="Hash User",
        username="hashuser",
        email="hashuser@test.org",
        role=User.ROLE_REVIEWER,
    )
    user.set_password("SecretPassword123")
    assert user.password_hash != "SecretPassword123"
    assert user.check_password("SecretPassword123") is True
    assert user.check_password("WrongPassword") is False


def test_login_success(client, super_admin_user, db_session):
    """Test successful login redirects and creates session & audit event."""
    response = client.post("/login", data={
        "username": "admin_test",
        "password": "AdminPass123"
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Welcome back, Admin Sharma" in response.data

    with client.session_transaction() as sess:
        assert sess.get("user_id") == super_admin_user.id
        assert sess.get("role") == User.ROLE_SUPER_ADMIN

    # Check audit log for login event
    event = db_session.query(AuditEvent).filter_by(action="LOGIN").first()
    assert event is not None
    assert event.actor_id == super_admin_user.id


def test_login_invalid_credentials(client, super_admin_user):
    """Test login with incorrect password fails cleanly with warning."""
    response = client.post("/login", data={
        "username": "admin_test",
        "password": "IncorrectPassword"
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Invalid credentials" in response.data


def test_logout(client, super_admin_user, db_session):
    """Test logout clears session and logs audit event."""
    client.post("/login", data={
        "username": "admin_test",
        "password": "AdminPass123"
    })

    response = client.get("/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"signed out securely" in response.data

    with client.session_transaction() as sess:
        assert "user_id" not in sess

    # Verify audit event
    logout_event = db_session.query(AuditEvent).filter_by(action="LOGOUT").first()
    assert logout_event is not None


def test_role_based_access_control(client, institution_admin_user):
    """Test institutional admin cannot access restricted super-admin audit log."""
    # Login as institutional admin
    client.post("/login", data={
        "username": "inst_admin_test",
        "password": "InstPass123"
    })

    # Try to access audit log
    response = client.get("/audit-log")
    assert response.status_code == 403
    assert b"Access Forbidden" in response.data
