import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from extensions import db
from models.user import User


def create_user(username, email, password, display_name, role="super_admin", institution_id=None):
    from app import create_app
    app = create_app()
    with app.app_context():
        existing = db.session.query(User).filter((User.username == username) | (User.email == email)).first()
        if existing:
            print(f"User '{username}' or email '{email}' already exists.")
            return existing

        user = User(
            username=username,
            email=email,
            display_name=display_name,
            role=role,
            institution_id=institution_id,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"User '{username}' ({role}) created successfully.")
        return user


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create administrative user for AICTE Portal")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", default="super_admin", choices=["super_admin", "reviewer", "institution_admin"])
    parser.add_argument("--institution-id", type=int, default=None)
    args = parser.parse_args()

    create_user(args.username, args.email, args.password, args.name, args.role, args.institution_id)
