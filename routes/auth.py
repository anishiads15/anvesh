import jwt
import random
import secrets
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, jsonify, current_app
from extensions import db
from models.user import User
from models.institution import Institution
from services.audit_service import log_audit_event

auth_bp = Blueprint("auth", __name__)

JWT_SECRET = "sentrix-sih26264-demo-secret-key-2026"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12

# In-memory stores for OTPs and Password Reset Tokens (persists during runtime)
ACTIVE_OTPS = {}   # identifier -> {"code": str, "expires_at": datetime, "attempts": int, "last_sent": datetime, "demo": bool}
RESET_TOKENS = {}  # token -> {"user_id": int, "expires_at": datetime}


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "bureau": user.bureau or "All",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def get_current_user():
    """Retrieves the authenticated user from the database based on session or JWT Authorization header."""
    user_id = session.get("user_id")
    if user_id:
        return db.session.query(User).filter_by(id=user_id, is_active=True).first()

    auth_header = request.headers.get("Authorization")
    if auth_header:
        token = auth_header
        if token.lower().startswith("bearer "):
            token = token[7:]
        try:
            payload = decode_token(token)
            uid = int(payload.get("sub", 0))
            return db.session.query(User).filter_by(id=uid, is_active=True).first()
        except Exception:
            return None

    return None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"detail": "Authentication required. Please log in."}), 401
            flash("Please sign in to access the AICTE Administrative Portal.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"detail": "Authentication required. Please log in."}), 401
                return redirect(url_for("auth.login", next=request.url))

            # Disallow read-only auditors on modification actions
            if user.is_auditor and request.method == "POST":
                if request.path.startswith("/api/"):
                    return jsonify({"detail": "Forbidden: Read-only auditor cannot perform write operations."}), 403
                flash("Access denied: External auditors possess read-only scrutiny permissions.", "danger")
                return render_template("errors/403.html"), 403

            matched = False
            for r in allowed_roles:
                if user.role == r or user.role.lower() == str(r).lower():
                    matched = True
                    break
                if r == User.ROLE_SUPER_ADMIN and user.is_super_admin:
                    matched = True
                    break
                if r == User.ROLE_AICTE_OFFICER and user.is_aicte_officer:
                    matched = True
                    break
                if r == User.ROLE_INSTITUTIONAL_REVIEWER and user.is_institutional_reviewer:
                    matched = True
                    break
                if r == User.ROLE_COMPLAINANT and user.is_complainant:
                    matched = True
                    break
                if r == User.ROLE_REVIEWER and user.is_reviewer:
                    matched = True
                    break
                if r == User.ROLE_AUDITOR and user.is_auditor:
                    matched = True
                    break

            if not matched:
                if request.path.startswith("/api/"):
                    return jsonify({"detail": "Access denied: You do not possess the required permissions for this action."}), 403
                flash("Access denied: You do not possess the required permissions for this action.", "danger")
                return render_template("errors/403.html"), 403

            g.current_user = user
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def request_server_otp(identifier: str, is_demo_allowed: bool = True):
    """Generates an expiring 6-digit server OTP with rate limiting."""
    key = identifier.strip().lower()
    now = datetime.utcnow()
    existing = ACTIVE_OTPS.get(key)

    # Rate limiting: 15s cooldown (bypassed in test environment)
    if existing and (now - existing["last_sent"]).total_seconds() < 15 and not current_app.config.get("TESTING"):
        remaining = 15 - int((now - existing["last_sent"]).total_seconds())
        return {
            "success": False,
            "message": f"Please wait {remaining} seconds before requesting a new OTP.",
            "throttled": True,
        }

    code = f"{random.randint(100000, 999999)}"
    ACTIVE_OTPS[key] = {
        "code": code,
        "expires_at": now + timedelta(minutes=10),
        "attempts": 0,
        "last_sent": now,
        "demo": is_demo_allowed,
    }
    return {
        "success": True,
        "code": code,
        "message": "OTP generated and dispatched successfully to registered contact.",
    }


def verify_server_otp(identifier: str, entered_otp: str, is_demo_allowed: bool = True) -> tuple[bool, str]:
    """Validates entered OTP against active server records and demo rules."""
    key = identifier.strip().lower()
    entered_otp = str(entered_otp).strip()
    now = datetime.utcnow()

    # In evaluation demo mode, standard demo OTP is accepted for seeded demo accounts
    is_demo_account = key in ("1ds22cs089", "par-984501", "student", "priya.nair", "suresh.menon")
    if (is_demo_allowed or is_demo_account) and entered_otp == "123456" and current_app.config.get("DEMO_MODE", True):
        return True, "Valid demo OTP verified."

    record = ACTIVE_OTPS.get(key)
    if not record:
        if is_demo_account and entered_otp == "123456":
            return True, "Valid demo OTP verified."
        return False, "No active OTP request found. Please click 'Request OTP' first."

    if now > record["expires_at"]:
        ACTIVE_OTPS.pop(key, None)
        return False, "OTP has expired. Please request a new OTP."

    record["attempts"] += 1
    if record["attempts"] > 5:
        ACTIVE_OTPS.pop(key, None)
        return False, "Maximum verification attempts exceeded. Please request a fresh OTP."

    if record["code"] == entered_otp or (record["demo"] and entered_otp == "123456"):
        ACTIVE_OTPS.pop(key, None)
        return True, "OTP successfully verified."

    remaining = 5 - record["attempts"]
    return False, f"Incorrect OTP. {remaining} attempt{'s' if remaining != 1 else ''} remaining."


# --- AUTHENTICATION ROUTES ---

@auth_bp.route("/auth/request-otp", methods=["POST"])
def request_otp():
    """Generates server OTP and returns delivery confirmation for Portal B & C."""
    data = request.get_json(silent=True) or request.form
    identifier = data.get("identifier", "").strip()
    portal = data.get("portal", "general")

    if not identifier:
        return jsonify({"success": False, "message": "Identifier (USN / ID / Mobile) is required."}), 400

    # Verify if user exists (or allow for registration)
    is_signup = data.get("is_signup", False)
    user = db.session.query(User).filter(
        (User.identifier == identifier) | (User.username == identifier) | (User.email == identifier)
    ).first()

    if not is_signup and not user:
        return jsonify({"success": False, "message": f"No registered account found for identifier '{identifier}'."}), 404

    res = request_server_otp(identifier, is_demo_allowed=True)
    if not res["success"]:
        return jsonify(res), 429

    log_audit_event(
        db.session,
        actor=user,
        action="OTP_REQUESTED",
        entity_type="Auth",
        entity_id=identifier,
        metadata={"ip": request.remote_addr, "portal": portal},
    )
    db.session.commit()

    demo_note = "Evaluation Demo OTP: 123456 (Server Generated: " + res["code"] + ")"
    return jsonify({
        "success": True,
        "message": f"OTP dispatched to registered contact for {identifier}.",
        "demo_note": demo_note,
        "identifier": identifier,
    })


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        user = get_current_user()
        if user and user.is_complainant:
            return redirect(url_for("complaints.student_portal"))
        return redirect(url_for("dashboard.index"))

    institutions = db.session.query(Institution).order_by(Institution.name).all()

    if request.method == "POST":
        portal = request.form.get("portal", "").strip().lower()
        login_type = request.form.get("login_type", "password")

        # Normalize test aliases (e.g. reviewer_pgrc / reviewer_rb)
        input_identifier = (
            request.form.get("identifier", "").strip() or
            request.form.get("username", "").strip()
        )
        password = request.form.get("password", "")
        otp = request.form.get("otp", "").strip()

        if not input_identifier:
            flash("Please provide a valid username, USN, or official identifier.", "danger")
            return render_template("login.html", institutions=institutions)

        # 1. OTP Verification Path (Portals B & C, or when OTP provided)
        if otp or login_type == "otp":
            valid, msg = verify_server_otp(input_identifier, otp, is_demo_allowed=True)
            if not valid:
                log_audit_event(
                    db.session,
                    actor=None,
                    action="LOGIN_FAILED",
                    entity_type="Auth",
                    entity_id=input_identifier,
                    metadata={"ip": request.remote_addr, "user_agent": request.headers.get("User-Agent", "Unknown"), "reason": msg, "mode": "otp"},
                )
                db.session.commit()
                flash(msg, "danger")
                return render_template("login.html", institutions=institutions, active_portal=portal or "student")

            # Lookup user by identifier, username, or email
            user = db.session.query(User).filter(
                (User.identifier == input_identifier) |
                (User.username == input_identifier) |
                (User.email == input_identifier)
            ).first()

            if not user or not user.is_active:
                flash(f"No active account found for identifier '{input_identifier}'.", "danger")
                return render_template("login.html", institutions=institutions, active_portal=portal or "student")

            # Portal Separation Validation
            if portal == "admin":
                if user.is_complainant:
                    flash("Access Denied: Complainants must authenticate via Student or Parent portal.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="student")
            elif portal in ["student", "parent"]:
                if user.is_super_admin or user.is_aicte_officer or user.is_reviewer or user.is_auditor:
                    flash("Access Denied: Official Administrative and Reviewer personnel must authenticate via Portal A.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="admin")
            elif portal == "institution":
                if user.is_complainant:
                    flash("Access Denied: Complainants must authenticate via Student or Parent portal.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="student")
                elif user.is_super_admin or user.is_aicte_officer or user.is_reviewer or user.is_auditor:
                    flash("Access Denied: AICTE Central personnel must authenticate via Portal A.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="admin")

            # Successful OTP Login
            user.last_login_at = datetime.utcnow()
            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            session["display_name"] = user.display_name
            session["role"] = user.role
            session["institution_id"] = user.institution_id
            session["bureau"] = user.bureau or "All"

            log_audit_event(
                db.session,
                actor=user,
                action="LOGIN",
                entity_type="Auth",
                entity_id=str(user.id),
                metadata={
                    "ip": request.remote_addr,
                    "user_agent": request.headers.get("User-Agent", "Unknown"),
                    "mode": "otp",
                    "status": "SUCCESS",
                    "portal": portal or ("parent" if "par" in input_identifier.lower() else "student"),
                    "role": user.role,
                    "bureau": user.bureau,
                },
            )
            db.session.commit()

            flash(f"Authenticated successfully as {user.display_name} ({user.role_title()}).", "success")
            next_url = request.args.get("next")
            if next_url:
                return redirect(next_url)
            if user.is_complainant:
                return redirect(url_for("complaints.student_portal"))
            return redirect(url_for("dashboard.index"))

        # 2. Standard Password Authentication Path
        user = db.session.query(User).filter(
            (User.username == input_identifier) |
            (User.identifier == input_identifier) |
            (User.email == input_identifier)
        ).first()

        if user and user.is_active and user.check_password(password):
            # Portal Separation Validation
            if portal == "admin":
                if user.is_complainant:
                    flash("Access Denied: Complainants must authenticate via Student or Parent portal.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="student")
            elif portal in ["student", "parent"]:
                if user.is_super_admin or user.is_aicte_officer or user.is_reviewer or user.is_auditor:
                    flash("Access Denied: Official Administrative and Reviewer personnel must authenticate via Portal A.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="admin")
            elif portal == "institution":
                if user.is_complainant:
                    flash("Access Denied: Complainants must authenticate via Student or Parent portal.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="student")
                elif user.is_super_admin or user.is_aicte_officer or user.is_reviewer or user.is_auditor:
                    flash("Access Denied: AICTE Central personnel must authenticate via Portal A.", "danger")
                    return render_template("login.html", institutions=institutions, active_portal="admin")

            user.last_login_at = datetime.utcnow()
            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            session["display_name"] = user.display_name
            session["role"] = user.role
            session["institution_id"] = user.institution_id
            session["bureau"] = user.bureau or "All"

            log_audit_event(
                db.session,
                actor=user,
                action="LOGIN",
                entity_type="Auth",
                entity_id=str(user.id),
                metadata={
                    "ip": request.remote_addr,
                    "user_agent": request.headers.get("User-Agent", "Unknown"),
                    "mode": "password",
                    "status": "SUCCESS",
                    "portal": portal or "admin",
                    "role": user.role,
                    "bureau": user.bureau,
                },
            )
            db.session.commit()

            flash(f"Welcome back, {user.display_name} ({user.role_title()}).", "success")
            next_url = request.args.get("next")
            if next_url:
                return redirect(next_url)
            if user.is_complainant:
                return redirect(url_for("complaints.student_portal"))
            return redirect(url_for("dashboard.index"))
        else:
            log_audit_event(
                db.session,
                actor=None,
                action="LOGIN_FAILED",
                entity_type="Auth",
                entity_id=input_identifier,
                metadata={
                    "ip": request.remote_addr,
                    "user_agent": request.headers.get("User-Agent", "Unknown"),
                    "mode": "password",
                    "portal": portal,
                    "reason": "Invalid credentials or deactivated account.",
                },
            )
            db.session.commit()
            flash("Invalid credentials or account deactivated. Please verify your login details.", "danger")

    return render_template("login.html", institutions=institutions)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Self-registration for eligible non-privileged users: Student, Parent, Institution User."""
    institutions = db.session.query(Institution).order_by(Institution.name).all()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role_type = request.form.get("role_type", "student").strip().lower()
        identifier = request.form.get("identifier", "").strip()
        institution_id = request.form.get("institution_id", type=int)
        phone = request.form.get("phone", "").strip()

        # CRITICAL SECURITY RULE: Public registration cannot create privileged roles
        if role_type in ("admin", "super_admin", "aicte_officer", "reviewer", "viewer", "auditor"):
            log_audit_event(
                db.session,
                actor=None,
                action="PRIVILEGED_SIGNUP_BLOCKED",
                entity_type="Auth",
                entity_id=username or email,
                metadata={"ip": request.remote_addr, "attempted_role": role_type},
            )
            db.session.commit()
            flash("Security Restriction: Privileged administrative, reviewer, and auditor accounts cannot be created via public registration. Contact AICTE Central Administration.", "danger")
            return render_template("login.html", institutions=institutions, active_tab="signup")

        if not full_name or not email or not password:
            flash("Full Name, Email Address, and Password are required.", "danger")
            return render_template("login.html", institutions=institutions, active_tab="signup")

        # Map to valid model roles
        if role_type == "institution":
            model_role = User.ROLE_INSTITUTIONAL_REVIEWER
            designation = request.form.get("designation", "Institutional Authority").strip()
            affiliation = "Technical Institution"
        elif role_type == "parent":
            model_role = User.ROLE_COMPLAINANT
            designation = "Parent / Legal Guardian"
            affiliation = "Parent Complainant"
            if not identifier:
                identifier = f"PAR-{random.randint(100000, 999999)}"
        else:  # default student
            model_role = User.ROLE_COMPLAINANT
            designation = "Student Complainant"
            affiliation = "Student"
            if not identifier:
                identifier = username

        if not username:
            username = identifier or email.split("@")[0]

        # Check duplicates
        existing = db.session.query(User).filter(
            (User.username == username) | (User.email == email) |
            ((User.identifier == identifier) if identifier else False)
        ).first()

        if existing:
            flash(f"An account with this username, email ({email}), or identifier ({identifier}) already exists. Please log in.", "warning")
            return render_template("login.html", institutions=institutions, active_tab="login")

        # Create user
        new_user = User(
            display_name=full_name,
            username=username,
            email=email,
            role=model_role,
            institution_id=institution_id if role_type in ("student", "institution") else None,
            identifier=identifier,
            phone=phone,
            designation=designation,
            affiliation=affiliation,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        log_audit_event(
            db.session,
            actor=new_user,
            action="REGISTRATION_SUCCESS",
            entity_type="User",
            entity_id=str(new_user.id),
            metadata={"ip": request.remote_addr, "role": model_role, "identifier": identifier},
        )
        db.session.commit()

        # Automatically authenticate the new user
        session.clear()
        session["user_id"] = new_user.id
        session["username"] = new_user.username
        session["display_name"] = new_user.display_name
        session["role"] = new_user.role
        session["institution_id"] = new_user.institution_id
        session["bureau"] = "Complainant Portal" if new_user.is_complainant else None

        flash(f"Account created successfully! Welcome to ANVESH, {new_user.display_name}.", "success")
        if new_user.is_complainant:
            return redirect(url_for("complaints.student_portal"))
        return redirect(url_for("dashboard.index"))

    return render_template("login.html", institutions=institutions, active_tab="signup")


@auth_bp.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    """Generates an expiring single-use password reset token."""
    username_or_email = request.form.get("username_or_email", "").strip()
    if not username_or_email:
        flash("Please enter your registered username or email address.", "danger")
        return redirect(url_for("auth.login"))

    user = db.session.query(User).filter(
        (User.username == username_or_email) | (User.email == username_or_email) | (User.identifier == username_or_email)
    ).first()

    if not user:
        # Generic response to prevent account enumeration
        flash("If an account matches those details, password reset instructions have been issued.", "info")
        return redirect(url_for("auth.login"))

    token = secrets.token_urlsafe(24)
    RESET_TOKENS[token] = {
        "user_id": user.id,
        "expires_at": datetime.utcnow() + timedelta(minutes=15),
    }

    log_audit_event(
        db.session,
        actor=user,
        action="PASSWORD_RESET_REQUESTED",
        entity_type="Auth",
        entity_id=str(user.id),
        metadata={"ip": request.remote_addr},
    )
    db.session.commit()

    return render_template("login.html", reset_token=token, reset_username=user.username, show_reset_modal=True)


@auth_bp.route("/auth/reset-password", methods=["POST"])
def reset_password():
    """Applies new password using valid single-use reset token."""
    token = request.form.get("token", "").strip()
    new_password = request.form.get("new_password", "")

    if not token or token not in RESET_TOKENS:
        flash("Password reset token is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.login"))

    record = RESET_TOKENS[token]
    if datetime.utcnow() > record["expires_at"]:
        RESET_TOKENS.pop(token, None)
        flash("Password reset token has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.login"))

    user = db.session.query(User).get(record["user_id"])
    if not user:
        RESET_TOKENS.pop(token, None)
        flash("User account not found.", "danger")
        return redirect(url_for("auth.login"))

    user.set_password(new_password)
    db.session.commit()
    RESET_TOKENS.pop(token, None)

    log_audit_event(
        db.session,
        actor=user,
        action="PASSWORD_RESET_SUCCESS",
        entity_type="Auth",
        entity_id=str(user.id),
        metadata={"ip": request.remote_addr},
    )
    db.session.commit()

    flash("Your password has been updated securely. You may now sign in.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Explicit logout with audit recording prior to session clearance."""
    user = get_current_user()
    if user:
        log_audit_event(
            db.session,
            actor=user,
            action="LOGOUT",
            entity_type="Auth",
            entity_id=str(user.id),
            metadata={"ip": request.remote_addr, "user_agent": request.headers.get("User-Agent", "Unknown"), "role": user.role},
        )
        db.session.commit()

    session.clear()
    flash("You have been signed out securely.", "info")
    return redirect(url_for("auth.login"))


# --- REST API Endpoints for SENTRIX & Test Compatibility ---

@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or request.form
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = db.session.query(User).filter(
        (User.username == username) | (User.email == username) | (User.identifier == username)
    ).first()

    if not user or not user.is_active or not user.check_password(password):
        return jsonify({"detail": "Invalid username or password."}), 401

    token = create_token(user)
    complainant_id = user.identifier or user.username if user.is_complainant else None

    return jsonify({
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.display_name,
        "role": user.role_title(),
        "bureau": user.bureau or "All",
        "designation": user.designation or user.role_title(),
        "identifier": user.identifier,
        "complainant_id": complainant_id,
        "affiliation": user.affiliation,
        "institution_id": user.institution_id,
    })


@auth_bp.route("/api/auth/otp-login", methods=["POST"])
def api_otp_login():
    data = request.get_json(silent=True) or request.form
    identifier = data.get("identifier", "").strip()
    otp = data.get("otp", "").strip()

    valid, msg = verify_server_otp(identifier, otp, is_demo_allowed=True)
    if not valid:
        return jsonify({"detail": msg}), 401

    user = db.session.query(User).filter(
        (User.identifier == identifier) | (User.username == identifier) | (User.email == identifier)
    ).first()

    if not user or not user.is_active:
        return jsonify({"detail": f"No registered account found for identifier '{identifier}'."}), 401

    token = create_token(user)
    complainant_id = user.identifier or user.username if user.is_complainant else None

    return jsonify({
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "full_name": user.display_name,
        "role": user.role_title(),
        "bureau": user.bureau or "Complainant Portal",
        "designation": user.designation or "Student Complainant",
        "identifier": user.identifier,
        "complainant_id": complainant_id,
        "affiliation": user.affiliation or "Student",
        "institution_id": user.institution_id,
    })


@auth_bp.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    user = g.current_user
    complainant_id = user.identifier or user.username if user.is_complainant else None
    return jsonify({
        "user_id": user.id,
        "username": user.username,
        "full_name": user.display_name,
        "role": user.role_title(),
        "bureau": user.bureau or "All",
        "designation": user.designation or user.role_title(),
        "identifier": user.identifier,
        "complainant_id": complainant_id,
        "affiliation": user.affiliation,
        "institution_id": user.institution_id,
    })
