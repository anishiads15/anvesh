import pytest
import os
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import TestConfig
from app import create_app
from extensions import db
from models.institution import Institution
from models.user import User
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from models.audit import AuditEvent


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    return db.session


@pytest.fixture
def sample_institution(db_session):
    inst = Institution(
        name="ABC Engineering College",
        code="AICTE-ENG-001",
        institution_type="Engineering College",
        state="Maharashtra",
        district="Pune",
        contact_person="Dr. Anand Verma",
        contact_email="principal@abcengineering.edu.in",
    )
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def sample_institution_2(db_session):
    inst = Institution(
        name="National Institute of Technology",
        code="AICTE-ENG-002",
        institution_type="Technical University",
        state="Karnataka",
        district="Bengaluru",
    )
    db_session.add(inst)
    db_session.commit()
    return inst


@pytest.fixture
def super_admin_user(db_session):
    user = User(
        display_name="Admin Sharma",
        username="admin_test",
        email="admin_test@aicte-india.org",
        role=User.ROLE_SUPER_ADMIN,
        is_active=True,
    )
    user.set_password("AdminPass123")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def reviewer_user(db_session):
    user = User(
        display_name="Reviewer Patel",
        username="reviewer_test",
        email="reviewer_test@aicte-india.org",
        role=User.ROLE_REVIEWER,
        is_active=True,
    )
    user.set_password("ReviewerPass123")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def institution_admin_user(db_session, sample_institution):
    user = User(
        display_name="Inst Admin Verma",
        username="inst_admin_test",
        email="inst_admin_test@abcengineering.edu.in",
        role=User.ROLE_INSTITUTION_ADMIN,
        institution_id=sample_institution.id,
        is_active=True,
    )
    user.set_password("InstPass123")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def complainant_user(db_session, sample_institution):
    user = User(
        display_name="Rahul Verma",
        username="student_test",
        email="student_test@abcengineering.edu.in",
        role=User.ROLE_COMPLAINANT,
        institution_id=sample_institution.id,
        is_active=True,
    )
    user.set_password("StudentPass123")
    db_session.add(user)
    db_session.commit()
    return user
