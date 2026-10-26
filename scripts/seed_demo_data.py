import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure root project directory is on Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from extensions import db
from models.institution import Institution
from models.user import User
from models.complaint import Complaint, ComplaintStatusHistory
from models.overlap import OverlapRelationship
from models.group import RelatedComplaintGroup
from sqlalchemy import text
from models.audit import AuditEvent
from services.overlap_detection import calculate_overlap_score
from services.audit_service import log_audit_event
from services.routing_service import suggest_department_routing, DEST_PGRC, DEST_RC, DEST_INSTITUTIONAL, DEST_MANUAL


def ensure_schema_updated():
    """Applies non-destructive schema migrations for new columns in SQLite database."""
    with db.engine.connect() as conn:
        try:
            # Ensure related_complaint_groups table exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS related_complaint_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_reference VARCHAR(50) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    root_cause TEXT,
                    category VARCHAR(100) NOT NULL,
                    institution_id INTEGER,
                    status VARCHAR(50) NOT NULL DEFAULT 'Open',
                    resolution_summary TEXT,
                    resolved_at DATETIME,
                    resolved_by_user_id INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE SET NULL,
                    FOREIGN KEY (resolved_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """))

            res = conn.execute(text("PRAGMA table_info(complaints)")).fetchall()
            col_names = [r[1] for r in res]
            if col_names:
                if "complainant_name" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN complainant_name VARCHAR(120)"))
                if "is_confidential" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN is_confidential BOOLEAN DEFAULT 0"))
                if "is_demo" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN is_demo BOOLEAN DEFAULT 0"))
                if "complainant_user_id" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN complainant_user_id INTEGER"))
                if "official_remarks" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN official_remarks TEXT"))
                if "aicte_remarks" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN aicte_remarks TEXT"))
                if "public_resolution_statement" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN public_resolution_statement TEXT"))
                if "escalation_reason" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN escalation_reason TEXT"))
                if "escalated_at" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN escalated_at DATETIME"))
                if "attachment_filename" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN attachment_filename VARCHAR(255)"))
                if "feedback_rating" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN feedback_rating INTEGER"))
                if "feedback_notes" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN feedback_notes TEXT"))
                if "reopen_reason" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN reopen_reason TEXT"))

                # AI Routing and Shared Group fields
                if "suggested_destination" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN suggested_destination VARCHAR(50)"))
                if "routing_reason" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routing_reason TEXT"))
                if "routing_confidence" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routing_confidence FLOAT"))
                if "routing_requires_human_review" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routing_requires_human_review BOOLEAN DEFAULT 1"))
                if "routed_destination" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routed_destination VARCHAR(50)"))
                if "routed_by_user_id" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routed_by_user_id INTEGER"))
                if "routed_at" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routed_at DATETIME"))
                if "routing_decision" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routing_decision VARCHAR(50)"))
                if "routing_override_reason" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN routing_override_reason TEXT"))
                if "related_group_id" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN related_group_id INTEGER"))
                if "resolution_status" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN resolution_status VARCHAR(50) DEFAULT 'Not Yet Resolved'"))
                if "is_recurrence" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN is_recurrence BOOLEAN DEFAULT 0"))
                if "recurrence_notes" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN recurrence_notes TEXT"))

                # Extended SENTRIX SIH26264 Fields
                if "source_bureau" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN source_bureau VARCHAR(100)"))
                if "due_date" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN due_date DATETIME"))
                if "incident_date" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN incident_date DATETIME"))
                if "complainant_id_str" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN complainant_id_str VARCHAR(80)"))
                if "assigned_officer_name" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN assigned_officer_name VARCHAR(120)"))
                if "last_action_date" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN last_action_date DATETIME"))
                if "next_action_due" not in col_names:
                    conn.execute(text("ALTER TABLE complaints ADD COLUMN next_action_due DATETIME"))

            res_inst = conn.execute(text("PRAGMA table_info(institutions)")).fetchall()
            col_names_inst = [r[1] for r in res_inst]
            if col_names_inst:
                if "is_demo" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN is_demo BOOLEAN DEFAULT 0"))
                if "aicte_id" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN aicte_id VARCHAR(64)"))
                if "normalized_name" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN normalized_name VARCHAR(255)"))
                if "region" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN region VARCHAR(64)"))
                if "address" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN address TEXT"))
                if "pincode" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN pincode VARCHAR(16)"))
                if "approval_status" not in col_names_inst:
                    conn.execute(text("ALTER TABLE institutions ADD COLUMN approval_status VARCHAR(32) DEFAULT 'Approved'"))

            res_user = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            col_names_user = [r[1] for r in res_user]
            if col_names_user:
                if "bureau" not in col_names_user:
                    conn.execute(text("ALTER TABLE users ADD COLUMN bureau VARCHAR(100)"))
                if "designation" not in col_names_user:
                    conn.execute(text("ALTER TABLE users ADD COLUMN designation VARCHAR(150)"))
                if "identifier" not in col_names_user:
                    conn.execute(text("ALTER TABLE users ADD COLUMN identifier VARCHAR(80)"))
                if "phone" not in col_names_user:
                    conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
                if "affiliation" not in col_names_user:
                    conn.execute(text("ALTER TABLE users ADD COLUMN affiliation VARCHAR(100)"))

            conn.commit()
        except Exception as e:
            print(f"Schema update notice: {e}")

    ensure_demo_users_and_links()


def ensure_demo_users_and_links():
    """Ensures demo accounts for all 3 portals exist and demo complaints are appropriately linked."""
    now = datetime.utcnow()
    # 1. Complainant / Student
    student = db.session.query(User).filter_by(username="student").first()
    if not student:
        student = User(
            display_name="Rahul Verma (Student)",
            username="student",
            email="student@abcengineering.edu.in",
            role=User.ROLE_COMPLAINANT,
            is_active=True,
            created_at=now - timedelta(days=60),
        )
        student.set_password("Student@123")
        db.session.add(student)
        db.session.commit()
    else:
        if student.role != User.ROLE_COMPLAINANT:
            student.role = User.ROLE_COMPLAINANT
            db.session.commit()

    # 2. Institutional Reviewer
    inst_admin = db.session.query(User).filter_by(username="inst_admin").first()
    first_inst = db.session.query(Institution).filter_by(code="AICTE-ENG-001").first()
    if not inst_admin:
        inst_admin = User(
            display_name="Dr. Anand Verma",
            username="inst_admin",
            email="anand.verma@abcengineering.edu.in",
            role=User.ROLE_INSTITUTIONAL_REVIEWER,
            institution_id=first_inst.id if first_inst else None,
            is_active=True,
            created_at=now - timedelta(days=45),
        )
        inst_admin.set_password("InstAdmin@123")
        db.session.add(inst_admin)
        db.session.commit()
    else:
        if inst_admin.role not in [User.ROLE_INSTITUTIONAL_REVIEWER, User.ROLE_INSTITUTION_ADMIN]:
            inst_admin.role = User.ROLE_INSTITUTIONAL_REVIEWER
        if first_inst and not inst_admin.institution_id:
            inst_admin.institution_id = first_inst.id
        db.session.commit()

    # 3. AICTE Officer
    super_admin = db.session.query(User).filter_by(username="admin").first()
    if not super_admin:
        super_admin = User(
            display_name="Dr. Rajiv Sharma",
            username="admin",
            email="admin@aicte-india.org",
            role=User.ROLE_AICTE_OFFICER,
            is_active=True,
            created_at=now - timedelta(days=90),
        )
        super_admin.set_password("Admin@123")
        db.session.add(super_admin)
        db.session.commit()
    else:
        if super_admin.role not in [User.ROLE_AICTE_OFFICER, User.ROLE_SUPER_ADMIN]:
            super_admin.role = User.ROLE_AICTE_OFFICER
        db.session.commit()

    # 4. Reviewer
    reviewer = db.session.query(User).filter_by(username="reviewer").first()
    if not reviewer:
        reviewer = User(
            display_name="Prof. Sunita Patel",
            username="reviewer",
            email="spatel.reviewer@aicte-india.org",
            role=User.ROLE_REVIEWER,
            is_active=True,
            created_at=now - timedelta(days=60),
        )
        reviewer.set_password("Reviewer@123")
        db.session.add(reviewer)
        db.session.commit()

    # Link some sample complaints to student user and populate workflow fields
    student_complaints = db.session.query(Complaint).filter(
        Complaint.reference_number.in_(["AICTE-2026-CMP-0002", "AICTE-2026-CMP-0004", "AICTE-2026-CMP-0006", "AICTE-2026-CMP-0008"])
    ).all()
    for sc in student_complaints:
        if not sc.complainant_user_id:
            sc.complainant_user_id = student.id
        if sc.resolution_notes and not sc.public_resolution_statement:
            sc.public_resolution_statement = sc.resolution_notes
        if sc.status in ["Under Investigation", "Under Review", "Open"] and not sc.official_remarks:
            sc.official_remarks = "Grievance received and verified by departmental review committee."
        if sc.reference_number == "AICTE-2026-CMP-0002":
            sc.status = "Escalated to AICTE"
            sc.escalation_reason = "Laboratory equipment repair unaddressed by college after 14 days; requires AICTE regulatory intervention."
            sc.escalated_at = now - timedelta(days=10)
    db.session.commit()

    # Populate AI Routing Recommendations for demo complaints
    all_complaints = db.session.query(Complaint).all()
    for c in all_complaints:
        if not c.suggested_destination:
            routing = suggest_department_routing(c.title, c.description, c.category, c.institution.name if c.institution else "")
            c.suggested_destination = routing["suggested_destination"]
            c.routing_reason = routing["routing_reason"]
            c.routing_confidence = routing["confidence_score"]
            c.routing_requires_human_review = True
        if not c.resolution_status:
            c.resolution_status = "Resolved" if c.status in ["Resolved", "Closed"] else "Not Yet Resolved"

    # Seed demonstration Related Complaint Group AICTE-GRP-2026-0001
    first_inst = db.session.query(Institution).filter_by(code="AICTE-ENG-001").first()
    existing_grp = db.session.query(RelatedComplaintGroup).filter_by(group_reference="AICTE-GRP-2026-0001").first()
    if not existing_grp and first_inst:
        grp = RelatedComplaintGroup(
            group_reference="AICTE-GRP-2026-0001",
            title="Mechanical Laboratory Tensile Testing Apparatus Breakdown",
            description="Linked incident dossier regarding repeated non-functional workshop tensile machinery and testing equipment.",
            root_cause="Hydraulic seal leakage and expired vendor annual maintenance contract (AMC).",
            category="Laboratory Equipment and Infrastructure",
            institution_id=first_inst.id,
            status="Under Review",
            created_at=now - timedelta(days=14),
            updated_at=now - timedelta(days=2),
        )
        db.session.add(grp)
        db.session.flush()

        c1 = db.session.query(Complaint).filter_by(reference_number="AICTE-2026-CMP-0001").first()
        c2 = db.session.query(Complaint).filter_by(reference_number="AICTE-2026-CMP-0002").first()
        if c1:
            c1.related_group_id = grp.id
            c1.resolution_status = "Not Yet Resolved"
            c1.routed_destination = "Institutional Reviewer"
            c1.routing_decision = "Accepted"
        if c2:
            c2.related_group_id = grp.id
            c2.resolution_status = "Not Yet Resolved"
            c2.routed_destination = "PGRC"
            c2.routing_decision = "Accepted"

    db.session.commit()


def seed_database(force: bool = False):
    """Seeds a coherent, realistic synthetic demonstration dataset with exactly 8 institutions and 30 complaints."""
    print("Checking database tables...")
    db.create_all()
    ensure_schema_updated()

    existing_demo_count = db.session.query(Complaint).filter_by(is_demo=True).count()
    if existing_demo_count == 30 and not force:
        print(f"Database already contains {existing_demo_count} demo complaints. Skipping duplicate seed.")
        return

    print("Cleaning existing demonstration records (preserving non-demo user data)...")
    target_refs = [f"AICTE-2026-CMP-{i:04d}" for i in range(1, 35)]
    demo_complaints = db.session.query(Complaint).filter(
        (Complaint.is_demo == True) | (Complaint.reference_number.in_(target_refs))
    ).all()
    demo_ids = [c.id for c in demo_complaints]

    if demo_ids:
        # Delete overlap relationships involving demo complaints
        db.session.query(OverlapRelationship).filter(
            (OverlapRelationship.first_complaint_id.in_(demo_ids)) |
            (OverlapRelationship.second_complaint_id.in_(demo_ids))
        ).delete(synchronize_session=False)

        # Delete status histories for demo complaints
        db.session.query(ComplaintStatusHistory).filter(
            ComplaintStatusHistory.complaint_id.in_(demo_ids)
        ).delete(synchronize_session=False)

        # Delete demo complaints
        db.session.query(Complaint).filter(Complaint.id.in_(demo_ids)).delete(synchronize_session=False)
        db.session.commit()

    # Clear demo institutions if re-seeding
    db.session.query(Institution).filter_by(is_demo=True).delete(synchronize_session=False)
    db.session.commit()

    print("Seeding exactly 8 Educational Institutions...")
    now = datetime.utcnow()

    institutions_data = [
        {
            "name": "ABC Engineering College",
            "code": "AICTE-ENG-001",
            "institution_type": "Engineering College",
            "state": "Maharashtra",
            "district": "Pune",
            "contact_person": "Dr. Anand Verma",
            "contact_email": "principal@abcengineering.edu.in",
            "contact_phone": "+91 (020) 2567-8901",
            "created_at": now - timedelta(days=120),
        },
        {
            "name": "National Institute of Science & Technology",
            "code": "AICTE-ENG-002",
            "institution_type": "Technical University",
            "state": "Karnataka",
            "district": "Bengaluru",
            "contact_person": "Prof. K. R. Narayanan",
            "contact_email": "registrar@nist-edu.in",
            "contact_phone": "+91 (080) 2890-1234",
            "created_at": now - timedelta(days=150),
        },
        {
            "name": "Delhi Technical Polytechnic Institute",
            "code": "AICTE-POLY-003",
            "institution_type": "Polytechnic",
            "state": "Delhi",
            "district": "North West Delhi",
            "contact_person": "Er. Meenakshi Sundaram",
            "contact_email": "director@delhipolytechnic.ac.in",
            "contact_phone": "+91 (011) 2765-4321",
            "created_at": now - timedelta(days=100),
        },
        {
            "name": "Chennai Institute of Advanced Technology",
            "code": "AICTE-ENG-004",
            "institution_type": "Engineering College",
            "state": "Tamil Nadu",
            "district": "Chennai",
            "contact_person": "Dr. V. Ramanathan",
            "contact_email": "grievances@ciat-chennai.edu.in",
            "contact_phone": "+91 (044) 2234-5678",
            "created_at": now - timedelta(days=90),
        },
        {
            "name": "Apex Institute of Engineering & Management",
            "code": "AICTE-ENG-005",
            "institution_type": "Engineering College",
            "state": "Rajasthan",
            "district": "Jaipur",
            "contact_person": "Dr. Sunita Choudhary",
            "contact_email": "dean@apexinstitute.ac.in",
            "contact_phone": "+91 (0141) 2780-1122",
            "created_at": now - timedelta(days=110),
        },
        {
            "name": "Vanguard Institute of Technology",
            "code": "AICTE-ENG-006",
            "institution_type": "Engineering College",
            "state": "Madhya Pradesh",
            "district": "Bhopal",
            "contact_person": "Prof. Rajeshwar Dixit",
            "contact_email": "principal@vanguardtech.edu.in",
            "contact_phone": "+91 (0755) 2678-4455",
            "created_at": now - timedelta(days=95),
        },
        {
            "name": "Kolkata Institute of Engineering & Technology",
            "code": "AICTE-ENG-007",
            "institution_type": "Engineering College",
            "state": "West Bengal",
            "district": "Kolkata",
            "contact_person": "Dr. Debabrata Roy",
            "contact_email": "grievance.cell@kiet-kolkata.org",
            "contact_phone": "+91 (033) 2456-7890",
            "created_at": now - timedelta(days=130),
        },
        {
            "name": "Doon College of Technology & Polytechnic",
            "code": "AICTE-POLY-008",
            "institution_type": "Polytechnic",
            "state": "Uttarakhand",
            "district": "Dehradun",
            "contact_person": "Er. Alok Semwal",
            "contact_email": "principal@doontechpoly.ac.in",
            "contact_phone": "+91 (0135) 2654-3210",
            "created_at": now - timedelta(days=85),
        },
    ]

    institutions = []
    for d in institutions_data:
        existing = db.session.query(Institution).filter_by(code=d["code"]).first()
        if not existing:
            inst = Institution(**d, is_demo=True)
            db.session.add(inst)
            institutions.append(inst)
        else:
            institutions.append(existing)

    db.session.commit()
    print(f"Verified {len(institutions)} Institutions.")

    # Demonstration Users
    print("Checking demonstration user accounts...")
    super_admin = db.session.query(User).filter_by(username="admin").first()
    if not super_admin:
        super_admin = User(
            display_name="Dr. Rajiv Sharma",
            username="admin",
            email="admin@aicte-india.org",
            role=User.ROLE_SUPER_ADMIN,
            is_active=True,
            created_at=now - timedelta(days=90),
        )
        super_admin.set_password("Admin@123")
        db.session.add(super_admin)

    reviewer = db.session.query(User).filter_by(username="reviewer").first()
    if not reviewer:
        reviewer = User(
            display_name="Prof. Sunita Patel",
            username="reviewer",
            email="spatel.reviewer@aicte-india.org",
            role=User.ROLE_REVIEWER,
            is_active=True,
            created_at=now - timedelta(days=60),
        )
        reviewer.set_password("Reviewer@123")
        db.session.add(reviewer)

    inst_admin = db.session.query(User).filter_by(username="inst_admin").first()
    if not inst_admin:
        inst_admin = User(
            display_name="Dr. Anand Verma",
            username="inst_admin",
            email="anand.verma@abcengineering.edu.in",
            role=User.ROLE_INSTITUTION_ADMIN,
            institution_id=institutions[0].id,
            is_active=True,
            created_at=now - timedelta(days=45),
        )
        inst_admin.set_password("InstAdmin@123")
        db.session.add(inst_admin)

    db.session.commit()

    # Map institutions by index (0-7)
    i1, i2, i3, i4, i5, i6, i7, i8 = institutions

    print("Seeding exactly 30 unique sample complaints across 8 institutions...")
    complaints_data = [
        # --- ABC Engineering College (i1) - 6 complaints ---
        {
            "ref": "AICTE-2026-CMP-0001",
            "title": "Mechanical engineering laboratory tensile testing machines non-functional",
            "desc": "The mechanical engineering laboratory testing equipment has remained non-functional for two weeks. Workshop machinery and tensile testing apparatus have broken down, severely disrupting practical sessions.",
            "inst": i1,
            "channel": "Institutional report",
            "cat": "Laboratory Equipment and Infrastructure",
            "subcat": "Non-functional apparatus",
            "priority": "High",
            "status": "Under Investigation",
            "complainant": "Prof. S. R. Joshi (HOD Mech)",
            "confidential": False,
            "days_ago": 24,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0002",
            "title": "Students cannot conduct practical experiments due to broken lab machines",
            "desc": "Students cannot conduct practical experiments because the mechanical department's lab machines and apparatus are broken down and completely out of order.",
            "inst": i1,
            "channel": "Student grievance",
            "cat": "Laboratory Equipment and Infrastructure",
            "subcat": "Non-functional apparatus",
            "priority": "High",
            "status": "Open",
            "complainant": "Mechanical Student Council",
            "confidential": False,
            "days_ago": 18,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0003",
            "title": "Campus drinking-water purifier in block B not functioning",
            "desc": "The college drinking-water purifier in academic block B is not functioning. Students have to buy bottled water and the water dispensers are leaking unhygienic water.",
            "inst": i1,
            "channel": "Student grievance",
            "cat": "Sanitation and Drinking Water",
            "subcat": "Water purifier breakdown",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Pooja Deshmukh",
            "confidential": False,
            "days_ago": 14,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0004",
            "title": "Classroom 302 electrical wiring sparking and broken ceiling fans",
            "desc": "Classroom 302 ceiling fans are not working and the main electrical switchboard sparks intermittently during lectures, creating a fire and short circuit danger.",
            "inst": i1,
            "channel": "Inspection report",
            "cat": "Safety and Security",
            "subcat": "Electrical hazard",
            "priority": "High",
            "status": "Resolved",
            "complainant": "Er. P. K. Shinde",
            "confidential": False,
            "days_ago": 75,
            "res_notes": "Internal wiring in classroom 302 completely replaced by certified campus electrical division and inspected.",
            "res_days": 50,
        },
        {
            "ref": "AICTE-2026-CMP-0005",
            "title": "Electrical switchboard short circuit sparks in classroom 302 recurring",
            "desc": "Electrical sparks and burning smell from ceiling switchboard in classroom 302 recurring during afternoon sessions, creating student panic.",
            "inst": i1,
            "channel": "Student grievance",
            "cat": "Safety and Security",
            "subcat": "Electrical hazard",
            "priority": "Critical",
            "status": "Under Investigation",
            "complainant": "Third Year Electrical Batch",
            "confidential": False,
            "days_ago": 12,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0006",
            "title": "Central library lacks updated syllabus textbooks and digital journal access",
            "desc": "Prescribed curriculum textbooks for third-year engineering are unavailable in the library, and electronic subscriptions to IEEE and ScienceDirect portals have lapsed.",
            "inst": i1,
            "channel": "Student grievance",
            "cat": "Library and Learning Resources",
            "subcat": "Deficit of textbooks & references",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Aditya Kulkarni",
            "confidential": False,
            "days_ago": 45,
            "res_notes": None,
            "res_days": None,
        },

        # --- National Institute of Science & Technology (i2) - 4 complaints ---
        {
            "ref": "AICTE-2026-CMP-0007",
            "title": "Delayed disbursal of post-matric AICTE Pragati scholarship funds",
            "desc": "Eligible female engineering students have not received their sanctioned AICTE Pragati scholarship funds for two semesters despite biometric validation.",
            "inst": i2,
            "channel": "Public grievance",
            "cat": "Scholarship Delays",
            "subcat": "AICTE Pragati / Saksham delay",
            "priority": "High",
            "status": "Pending",
            "complainant": "Sneha Reddy & Peers",
            "confidential": False,
            "days_ago": 65,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0008",
            "title": "Workshop lathe machines and power tools out of order",
            "desc": "Lathe machines and welding apparatus in the manufacturing workshop have broken down, preventing students from completing fabrication projects.",
            "inst": i2,
            "channel": "Student grievance",
            "cat": "Laboratory Equipment and Infrastructure",
            "subcat": "Non-functional apparatus",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Kiran Kumar",
            "confidential": False,
            "days_ago": 28,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0009",
            "title": "Withholding of caution deposit refund after graduation",
            "desc": "College accounts office refuses to refund mandatory caution deposits and library securities to graduating batch students.",
            "inst": i2,
            "channel": "Public grievance",
            "cat": "Financial Issues and Fee Irregularities",
            "subcat": "Refusal of tuition refund",
            "priority": "Medium",
            "status": "Resolved",
            "complainant": "NIST Alumni Association",
            "confidential": False,
            "days_ago": 38,
            "res_notes": "Formal directive issued by Regional Office. Institute accounts section processed all refunds via direct bank transfer.",
            "res_days": 15,
        },
        {
            "ref": "AICTE-2026-CMP-0010",
            "title": "Denial of hostel single-room accommodation to student with physical disability",
            "desc": "Differently-abled student using wheelchair was denied ground floor accessible hostel accommodation by management, forcing daily staircase climbing.",
            "inst": i2,
            "channel": "Confidential report",
            "cat": "Discrimination and Student Welfare",
            "subcat": "Differently-abled student neglect",
            "priority": "Critical",
            "status": "Open",
            "complainant": "Ramesh Kumar",
            "confidential": True,
            "days_ago": 10,
            "res_notes": None,
            "res_days": None,
        },

        # --- Delhi Technical Polytechnic Institute (i3) - 4 complaints ---
        {
            "ref": "AICTE-2026-CMP-0011",
            "title": "Severe shortage of qualified teaching faculty in computer science department",
            "desc": "Severe shortage of qualified computer science faculty. Core subjects including Operating Systems and Algorithms remain uncovered due to vacant professor posts.",
            "inst": i3,
            "channel": "Student grievance",
            "cat": "Faculty Misconduct",
            "subcat": "Faculty shortage & absenteeism",
            "priority": "Critical",
            "status": "Under Investigation",
            "complainant": "Diploma CS Students Group",
            "confidential": False,
            "days_ago": 50,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0012",
            "title": "Lecturers absent for three weeks without syllabus coverage in computing subjects",
            "desc": "Computer engineering department instructors and lecturers have remained absent for three weeks without any substitute teaching staff or class conduction.",
            "inst": i3,
            "channel": "Student grievance",
            "cat": "Faculty Misconduct",
            "subcat": "Faculty shortage & absenteeism",
            "priority": "High",
            "status": "Open",
            "complainant": "Rohit Verma",
            "confidential": False,
            "days_ago": 42,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0013",
            "title": "Mid-semester examination timetable announced with zero preparation notice",
            "desc": "Polytechnic examination controller published diploma end-term timetable with only 24 hours notice, conflicting with national holiday schedules.",
            "inst": i3,
            "channel": "Student grievance",
            "cat": "Academic and Examination Issues",
            "subcat": "Examination schedule disruption",
            "priority": "Medium",
            "status": "Pending",
            "complainant": "General Student Body",
            "confidential": False,
            "days_ago": 20,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0014",
            "title": "Restroom hygiene deplorable with no running tap water in polytechnic wing",
            "desc": "Toilets on the second floor have no running water and choked drainage pipes, creating foul odors and unhygienic conditions for students.",
            "inst": i3,
            "channel": "Student grievance",
            "cat": "Sanitation and Drinking Water",
            "subcat": "Restroom & washroom cleanliness",
            "priority": "High",
            "status": "Open",
            "complainant": "Deepak Gupta",
            "confidential": False,
            "days_ago": 8,
            "res_notes": None,
            "res_days": None,
        },

        # --- Chennai Institute of Advanced Technology (i4) - 4 complaints ---
        {
            "ref": "AICTE-2026-CMP-0015",
            "title": "Hostel mess food quality substandard causing stomach infections",
            "desc": "Hostel mess is serving stale, unhygienic meals resulting in severe food poisoning, nausea, and hospitalization of residential students.",
            "inst": i4,
            "channel": "Public grievance",
            "cat": "Hostel and Accommodation",
            "subcat": "Mess & canteen food hygiene",
            "priority": "Critical",
            "status": "Under Investigation",
            "complainant": "Residential Students Welfare Association",
            "confidential": False,
            "days_ago": 30,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0016",
            "title": "Unhygienic student canteen food preparation and contaminated dining water",
            "desc": "Canteen food vendor uses unboiled, contaminated water and spoiled ingredients, resulting in gastrointestinal distress among hostel students.",
            "inst": i4,
            "channel": "Student grievance",
            "cat": "Hostel and Accommodation",
            "subcat": "Mess & canteen food hygiene",
            "priority": "High",
            "status": "Open",
            "complainant": "S. Karthik",
            "confidential": False,
            "days_ago": 25,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0017",
            "title": "Sanitation blockage and sewage overflow in ground floor academic block",
            "desc": "Ground floor washrooms in the academic building have blocked sewer lines resulting in wastewater overflowing into hallways.",
            "inst": i4,
            "channel": "Institutional report",
            "cat": "Sanitation and Drinking Water",
            "subcat": "Drainage and sewage overflow",
            "priority": "High",
            "status": "Resolved",
            "complainant": "Facility Supervisor",
            "confidential": False,
            "days_ago": 70,
            "res_notes": "Municipal drainage lines cleared and replacement pipes installed by plumbing contractor.",
            "res_days": 40,
        },
        {
            "ref": "AICTE-2026-CMP-0018",
            "title": "Severe sewage leakage and choked drainage pipes recurring in ground floor restrooms",
            "desc": "Restrooms on ground floor academic building are overflowing again with wastewater and choked drains, repeating the earlier sanitation failure.",
            "inst": i4,
            "channel": "Student grievance",
            "cat": "Sanitation and Drinking Water",
            "subcat": "Drainage and sewage overflow",
            "priority": "Critical",
            "status": "Pending",
            "complainant": "M. Vignesh",
            "confidential": False,
            "days_ago": 10,
            "res_notes": None,
            "res_days": None,
        },

        # --- Apex Institute of Engineering & Management (i5) - 3 complaints ---
        {
            "ref": "AICTE-2026-CMP-0019",
            "title": "Deficit of latest engineering reference books and inactive digital library",
            "desc": "Deficit of prescribed textbooks, syllabus references, and inactive online IEEE and journal subscriptions in the main campus library.",
            "inst": i5,
            "channel": "Student grievance",
            "cat": "Library and Learning Resources",
            "subcat": "Deficit of textbooks & references",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Megha Rathore",
            "confidential": False,
            "days_ago": 38,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0020",
            "title": "Physical and verbal intimidation of first-year students in senior hostel",
            "desc": "Senior batch students in hostel block B subjected first-year students to late-night verbal intimidation, unauthorized drills, and psychological harassment.",
            "inst": i5,
            "channel": "Confidential report",
            "cat": "Ragging and Student Harassment",
            "subcat": "Hostel ragging incidents",
            "priority": "Critical",
            "status": "Under Investigation",
            "complainant": "Vikram Rathore",
            "confidential": True,
            "days_ago": 15,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0021",
            "title": "Mandatory capitation fee demanded under the label of campus development fund",
            "desc": "Administration is demanding unapproved mandatory development fees of Rs 25,000 before releasing semester examination admit cards.",
            "inst": i5,
            "channel": "Public grievance",
            "cat": "Financial Issues and Fee Irregularities",
            "subcat": "Capitation fee & overcharging",
            "priority": "High",
            "status": "Open",
            "complainant": "Parents Association Jaipur",
            "confidential": False,
            "days_ago": 5,
            "res_notes": None,
            "res_days": None,
        },

        # --- Vanguard Institute of Technology (i6) - 3 complaints ---
        {
            "ref": "AICTE-2026-CMP-0022",
            "title": "Hostel block A solar water geysers non-operational during winter",
            "desc": "Hostel block A hot water geysers and rooftop heating units have remained non-operational throughout the winter season, forcing students to bathe in freezing water.",
            "inst": i6,
            "channel": "Student grievance",
            "cat": "Hostel and Accommodation",
            "subcat": "Geyser and hot water failure",
            "priority": "Medium",
            "status": "Pending",
            "complainant": "Hostel Block A Inmates",
            "confidential": False,
            "days_ago": 35,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0023",
            "title": "Zero hot water supply in boys hostel wing A due to damaged rooftop water heating units",
            "desc": "Boys hostel wing A has had zero hot water supply for three weeks because all solar geysers and rooftop heating systems are damaged and unrepaired.",
            "inst": i6,
            "channel": "Student grievance",
            "cat": "Hostel and Accommodation",
            "subcat": "Geyser and hot water failure",
            "priority": "High",
            "status": "Open",
            "complainant": "Pradeep Rawat",
            "confidential": False,
            "days_ago": 30,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0024",
            "title": "Campus perimeter boundary wall collapsed near sports ground",
            "desc": "A fifty-foot section of the rear boundary wall collapsed, allowing stray animals and unauthorized intruders to enter the institute grounds at night.",
            "inst": i6,
            "channel": "Institutional report",
            "cat": "Safety and Security",
            "subcat": "Boundary wall and trespassers",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Security Officer",
            "confidential": False,
            "days_ago": 16,
            "res_notes": None,
            "res_days": None,
        },

        # --- Kolkata Institute of Engineering & Technology (i7) - 3 complaints ---
        {
            "ref": "AICTE-2026-CMP-0025",
            "title": "Delay in crediting technical education scholarship and state welfare stipends",
            "desc": "Technical education scholarship and state government welfare stipends have not been credited to student bank accounts due to pending verification at institute level.",
            "inst": i7,
            "channel": "Public grievance",
            "cat": "Scholarship Delays",
            "subcat": "State welfare stipend pending",
            "priority": "High",
            "status": "Open",
            "complainant": "Tathagata Banerjee",
            "confidential": False,
            "days_ago": 60,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0026",
            "title": "Refusal to return original marksheets and degree certificates upon course completion",
            "desc": "College registrar is refusing to hand over original school certificates and undergraduate degrees unless arbitrary placement fees are paid.",
            "inst": i7,
            "channel": "Student grievance",
            "cat": "Financial Issues and Fee Irregularities",
            "subcat": "Document withholding for fees",
            "priority": "Critical",
            "status": "Under Investigation",
            "complainant": "Anirban Sen",
            "confidential": False,
            "days_ago": 22,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0027",
            "title": "Campus shuttle bus service cancelled without alternate transportation",
            "desc": "Student transportation shuttle buses connecting suburban metro stations to the campus have been suspended indefinitely, stranding commuting students.",
            "inst": i7,
            "channel": "Student grievance",
            "cat": "Other",
            "subcat": "Campus amenities & transportation",
            "priority": "Low",
            "status": "Open",
            "complainant": "Commuters Union",
            "confidential": False,
            "days_ago": 4,
            "res_notes": None,
            "res_days": None,
        },

        # --- Doon College of Technology & Polytechnic (i8) - 3 complaints ---
        {
            "ref": "AICTE-2026-CMP-0028",
            "title": "Non-functional fire extinguishers in polytechnic chemistry laboratory",
            "desc": "All fire extinguishers in the chemistry lab and mechanical workshop are expired by over two years with empty pressure gauges.",
            "inst": i8,
            "channel": "Inspection report",
            "cat": "Safety and Security",
            "subcat": "Fire safety non-compliance",
            "priority": "High",
            "status": "Resolved",
            "complainant": "Er. Alok Semwal",
            "confidential": False,
            "days_ago": 55,
            "res_notes": "All laboratory fire extinguishers refilled and certified compliant with state fire department regulations.",
            "res_days": 20,
        },
        {
            "ref": "AICTE-2026-CMP-0029",
            "title": "Laboratory practical marks deducted arbitrarily without evaluation rubric",
            "desc": "Faculty external examiner deducted practical marks across an entire section without conducting viva voce or referencing AICTE rubrics.",
            "inst": i8,
            "channel": "Student grievance",
            "cat": "Academic and Examination Issues",
            "subcat": "Evaluation irregularities",
            "priority": "Medium",
            "status": "Open",
            "complainant": "Sunil Negi",
            "confidential": False,
            "days_ago": 18,
            "res_notes": None,
            "res_days": None,
        },
        {
            "ref": "AICTE-2026-CMP-0030",
            "title": "Absence of internal complaints committee and grievance redressal cell",
            "desc": "The institute has failed to constitute a functional Internal Complaints Committee (ICC) and student grievance portal as mandated by AICTE regulations.",
            "inst": i8,
            "channel": "Confidential report",
            "cat": "Discrimination and Student Welfare",
            "subcat": "Welfare committee inactivity",
            "priority": "High",
            "status": "Open",
            "complainant": "Ananya Sharma",
            "confidential": True,
            "days_ago": 7,
            "res_notes": None,
            "res_days": None,
        },
    ]

    seeded_complaints = []
    for item in complaints_data:
        c_date = now - timedelta(days=item["days_ago"])
        r_date = (now - timedelta(days=item["res_days"])) if item.get("res_days") else None
        routing_info = suggest_department_routing(item["title"], item["desc"], item["cat"], item["inst"].name)

        c = Complaint(
            reference_number=item["ref"],
            title=item["title"],
            description=item["desc"],
            institution_id=item["inst"].id,
            source_channel=item["channel"],
            category=item["cat"],
            subcategory=item["subcat"],
            priority=item["priority"],
            status=item["status"],
            complainant_name=item["complainant"],
            is_confidential=item["confidential"],
            is_demo=True,
            suggested_destination=routing_info["suggested_destination"],
            routing_reason=routing_info["routing_reason"],
            routing_confidence=routing_info["confidence_score"],
            routing_requires_human_review=True,
            resolution_status="Resolved" if item["status"] in ["Resolved", "Closed"] else "Not Yet Resolved",
            assigned_reviewer_id=reviewer.id if item["status"] in ["Under Investigation", "Resolved", "Pending"] else None,
            resolution_notes=item["res_notes"],
            resolution_date=r_date,
            categorization_source="AI - Semantic Model (MiniLM + Hybrid Keyword)",
            categorization_confidence=0.92,
            created_at=c_date,
            updated_at=r_date if r_date else (c_date + timedelta(days=1)),
        )
        db.session.add(c)
        seeded_complaints.append(c)

    db.session.commit()
    print(f"Successfully inserted {len(seeded_complaints)} unique demo complaints.")

    # Status Histories for Lifecycle Tracking
    print("Writing initial lifecycle status logs...")
    for c in seeded_complaints:
        db.session.add(ComplaintStatusHistory(
            complaint_id=c.id,
            previous_status=None,
            new_status="Open",
            actor_name="AICTE Grievance Intake Portal",
            notes="Formal grievance received through portal intake.",
            timestamp=c.created_at,
        ))
        if c.status != "Open":
            db.session.add(ComplaintStatusHistory(
                complaint_id=c.id,
                previous_status="Open",
                new_status=c.status,
                actor_id=reviewer.id,
                actor_name=reviewer.display_name,
                notes=c.resolution_notes or f"Grievance review state updated to {c.status}.",
                timestamp=c.updated_at,
            ))
    db.session.commit()

    print("Running Overlap Detection Pipeline pairwise across all 30 complaints...")
    # Map complaints by reference for easy access
    ref_map = {c.reference_number: c for c in seeded_complaints}
    overlap_count = 0

    for i in range(len(seeded_complaints)):
        for j in range(i + 1, len(seeded_complaints)):
            ca = seeded_complaints[i]
            cb = seeded_complaints[j]
            res = calculate_overlap_score(ca, cb, allow_transformer=True)

            if res["similarity_score"] >= 0.50:
                first_id = min(ca.id, cb.id)
                second_id = max(ca.id, cb.id)

                rel = OverlapRelationship(
                    first_complaint_id=first_id,
                    second_complaint_id=second_id,
                    similarity_score=res["similarity_score"],
                    semantic_score=res["semantic_score"],
                    keyword_score=res["keyword_score"],
                    category_score=res["category_score"],
                    context_score=res["context_score"],
                    relationship_type=res["relationship_type"],
                    review_status="Pending Review",
                    matching_evidence=res["matching_evidence"],
                    conflicting_evidence=res["conflicting_evidence"],
                    algorithm_version=res["algorithm_version"],
                    created_at=now,
                )
                db.session.add(rel)
                overlap_count += 1

    db.session.commit()
    print(f"Overlap detection complete: {overlap_count} relationships identified.")

    # Mark 2 representative relationships as Human-Confirmed to demonstrate reviewer workflow
    print("Setting human confirmation on representative overlap records...")
    # 1. Strong Overlap at ABC College (CMP-0001 and CMP-0002)
    c1 = ref_map.get("AICTE-2026-CMP-0001")
    c2 = ref_map.get("AICTE-2026-CMP-0002")
    if c1 and c2:
        rel1 = db.session.query(OverlapRelationship).filter_by(
            first_complaint_id=min(c1.id, c2.id),
            second_complaint_id=max(c1.id, c2.id)
        ).first()
        if rel1:
            rel1.review_status = "Confirmed Related"
            rel1.relationship_type = "Human-Confirmed Related"
            rel1.reviewer_id = reviewer.id
            rel1.reviewed_at = now - timedelta(days=5)
            rel1.review_notes = "Administrative confirmation: Both grievances report identical mechanical lab testing machine failure. Consolidated for joint departmental inquiry."

    # 2. Confirmed Recurrence at ABC College (CMP-0004 and CMP-0005)
    c4 = ref_map.get("AICTE-2026-CMP-0004")
    c5 = ref_map.get("AICTE-2026-CMP-0005")
    if c4 and c5:
        rel2 = db.session.query(OverlapRelationship).filter_by(
            first_complaint_id=min(c4.id, c5.id),
            second_complaint_id=max(c4.id, c5.id)
        ).first()
        if rel2:
            rel2.review_status = "Confirmed Related"
            rel2.relationship_type = "Human-Confirmed Related"
            rel2.reviewer_id = reviewer.id
            rel2.reviewed_at = now - timedelta(days=2)
            rel2.review_notes = "Confirmed Recurrence: Classroom 302 electrical sparking recurred despite earlier reported resolution. Priority re-escalation issued to campus electrical wing."

    log_audit_event(
        db.session,
        actor=super_admin,
        action="SYSTEM_SEEDED",
        entity_type="Database",
        entity_id="AICTE-DEMO-DATASET",
        metadata={"institutions": 8, "complaints": 30, "overlaps": overlap_count},
    )

    db.session.commit()
    print("Demonstration dataset successfully initialized with exactly 8 institutions and 30 complaints!")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_database(force=True)
