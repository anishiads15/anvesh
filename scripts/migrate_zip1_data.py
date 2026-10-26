import sys
import os
import sqlite3
from datetime import datetime
from pathlib import Path

# Ensure root project directory is on Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app
from extensions import db
from models.institution import Institution
from models.user import User
from models.complaint import Complaint, ComplaintStatusHistory
from models.overlap import OverlapRelationship
from models.group import RelatedComplaintGroup
from models.audit import AuditEvent
from models.notification import Notification
from sqlalchemy import text
from scripts.seed_demo_data import ensure_schema_updated, seed_database


def run_migration():
    app = create_app()
    with app.app_context():
        print("=== Step 1: Upgrading Schema Non-Destructively ===")
        db.create_all()
        ensure_schema_updated()

        with db.engine.connect() as conn:
            # Upgrade complaints table
            res = conn.execute(text("PRAGMA table_info(complaints)")).fetchall()
            cols = [r[1] for r in res]
            if "source_bureau" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN source_bureau VARCHAR(100)"))
            if "due_date" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN due_date DATETIME"))
            if "incident_date" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN incident_date DATETIME"))
            if "complainant_id_str" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN complainant_id_str VARCHAR(80)"))
            if "assigned_officer_name" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN assigned_officer_name VARCHAR(120)"))
            if "last_action_date" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN last_action_date DATETIME"))
            if "next_action_due" not in cols:
                conn.execute(text("ALTER TABLE complaints ADD COLUMN next_action_due DATETIME"))

            # Upgrade institutions table
            res_inst = conn.execute(text("PRAGMA table_info(institutions)")).fetchall()
            cols_inst = [r[1] for r in res_inst]
            if "aicte_id" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN aicte_id VARCHAR(64)"))
            if "normalized_name" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN normalized_name VARCHAR(255)"))
            if "region" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN region VARCHAR(64)"))
            if "address" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN address TEXT"))
            if "pincode" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN pincode VARCHAR(16)"))
            if "approval_status" not in cols_inst:
                conn.execute(text("ALTER TABLE institutions ADD COLUMN approval_status VARCHAR(32) DEFAULT 'Approved'"))

            # Upgrade users table
            res_user = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            cols_user = [r[1] for r in res_user]
            if "bureau" not in cols_user:
                conn.execute(text("ALTER TABLE users ADD COLUMN bureau VARCHAR(100)"))
            if "designation" not in cols_user:
                conn.execute(text("ALTER TABLE users ADD COLUMN designation VARCHAR(150)"))
            if "identifier" not in cols_user:
                conn.execute(text("ALTER TABLE users ADD COLUMN identifier VARCHAR(80)"))
            if "phone" not in cols_user:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
            if "affiliation" not in cols_user:
                conn.execute(text("ALTER TABLE users ADD COLUMN affiliation VARCHAR(100)"))

            conn.commit()
            print("Schema extensions verified and applied.")

        # Ensure baseline seed records exist
        print("\n=== Step 2: Ensuring ZIP 2 Baseline Demo Data Exists ===")
        seed_database(force=False)

        # Connect to ZIP 1 database
        zip1_db_path = Path(r"C:\Users\Saichand\.gemini\antigravity\scratch\sentrix_master\extracted\zip1_sentrix_ready\SENTRIX\backend\sentrix.db")
        if not zip1_db_path.exists():
            print(f"Error: ZIP 1 db not found at {zip1_db_path}")
            return

        conn1 = sqlite3.connect(str(zip1_db_path))
        conn1.row_factory = sqlite3.Row
        cur1 = conn1.cursor()

        print("\n=== Step 3: Migrating ZIP 1 Institutions (40 records) ===")
        cur1.execute("SELECT * FROM institutions")
        inst_rows = cur1.fetchall()
        inst_map = {}  # zip1_id -> zip2_id

        for r in inst_rows:
            # Check by code or name
            code = r["aicte_id"]
            name = r["name"]
            existing = db.session.query(Institution).filter(
                (Institution.code == code) | (Institution.name == name)
            ).first()

            if existing:
                inst_map[r["id"]] = existing.id
                if not existing.aicte_id:
                    existing.aicte_id = code
                if not existing.normalized_name:
                    existing.normalized_name = r["normalized_name"]
                if not existing.region:
                    existing.region = r["region"]
                if not existing.address:
                    existing.address = r["address"]
                if not existing.pincode:
                    existing.pincode = r["pincode"]
            else:
                new_inst = Institution(
                    name=name,
                    code=code,
                    aicte_id=code,
                    normalized_name=r["normalized_name"],
                    institution_type=r["institution_type"] or "Engineering College",
                    region=r["region"],
                    state=r["state"],
                    district=r["district"],
                    address=r["address"],
                    pincode=r["pincode"],
                    contact_email=r["contact_email"],
                    contact_phone=r["contact_phone"],
                    contact_person=r["principal_name"],
                    approval_status=r["approval_status"] or "Approved",
                    is_demo=False,
                )
                db.session.add(new_inst)
                db.session.flush()
                inst_map[r["id"]] = new_inst.id

        db.session.commit()
        print(f"Mapped {len(inst_map)} institutions successfully.")

        print("\n=== Step 4: Migrating ZIP 1 Users ===")
        cur1.execute("SELECT * FROM users")
        user_rows = cur1.fetchall()
        user_map = {}  # zip1_id -> zip2_id

        for r in user_rows:
            username = r["username"]
            existing = db.session.query(User).filter_by(username=username).first()

            # Map ZIP 1 roles to ZIP 2 model roles
            role_map = {
                "Admin": User.ROLE_SUPER_ADMIN,
                "Bureau Officer": User.ROLE_REVIEWER,
                "Viewer": User.ROLE_AUDITOR,
                "Complainant": User.ROLE_COMPLAINANT,
            }
            mapped_role = role_map.get(r["role"], r["role"].lower())

            if existing:
                user_map[r["id"]] = existing.id
                existing.bureau = r["bureau"]
                existing.designation = r["designation"]
                existing.identifier = r["identifier"]
                existing.phone = r["phone"]
                existing.affiliation = r["affiliation"]
                # If admin, ensure display_name or extra info is stored
                if username == "admin":
                    existing.bureau = "All"
                    existing.designation = r["designation"]
            else:
                new_user = User(
                    username=username,
                    display_name=r["full_name"],
                    email=r["email"],
                    role=mapped_role,
                    bureau=r["bureau"],
                    designation=r["designation"],
                    identifier=r["identifier"],
                    phone=r["phone"],
                    affiliation=r["affiliation"],
                    password_hash=r["password_hash"],
                    is_active=bool(r["is_active"]),
                )
                db.session.add(new_user)
                db.session.flush()
                user_map[r["id"]] = new_user.id

        db.session.commit()
        print(f"Mapped {len(user_map)} users successfully.")

        print("\n=== Step 5: Migrating ZIP 1 Complaints (250 records) ===")
        cur1.execute("SELECT * FROM complaints")
        comp_rows = cur1.fetchall()
        comp_map = {}  # zip1_id -> zip2_id

        priya_user = db.session.query(User).filter_by(username="priya.nair").first()
        suresh_user = db.session.query(User).filter_by(username="suresh.menon").first()

        for r in comp_rows:
            case_id = r["case_id"]
            existing = db.session.query(Complaint).filter_by(reference_number=case_id).first()

            if existing:
                comp_map[r["id"]] = existing.id
                continue

            inst_id = inst_map.get(r["institution_id"])
            if not inst_id:
                # Fallback to first institution
                inst_id = db.session.query(Institution).first().id

            # Parse dates
            def parse_dt(val):
                if not val:
                    return None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val, fmt)
                    except ValueError:
                        pass
                return None

            created_at = parse_dt(r["received_date"]) or parse_dt(r["created_at"]) or datetime.utcnow()
            due_date = parse_dt(r["due_date"])
            updated_at = parse_dt(r["last_action_date"]) or parse_dt(r["updated_at"]) or created_at
            incident_date = parse_dt(r["incident_date"])
            res_date = parse_dt(r["disposed_date"])

            # Map complainant user
            comp_user_id = None
            if r["complainant_name"] == "Priya Nair" or r["complainant_id"] == "1DS22CS089":
                comp_user_id = priya_user.id if priya_user else None
            elif r["complainant_name"] == "Suresh Menon" or r["complainant_id"] == "PAR-984501":
                comp_user_id = suresh_user.id if suresh_user else None

            # Priority mapping
            priority = r["priority"]
            if priority == "Urgent":
                priority = "Critical"

            new_c = Complaint(
                reference_number=case_id,
                title=r["subject"],
                description=r["description"],
                institution_id=inst_id,
                source_channel=r["complainant_type"] or "Student grievance",
                category=r["category"],
                priority=priority,
                status=r["status"],
                complainant_name=r["complainant_name"],
                complainant_user_id=comp_user_id,
                complainant_id_str=r["complainant_id"],
                is_confidential=bool(r["is_anonymous"]),
                is_demo=False,
                source_bureau=r["source_bureau"],
                due_date=due_date,
                incident_date=incident_date,
                last_action_date=updated_at,
                next_action_due=parse_dt(r["next_action_due"]),
                assigned_officer_name=r["assigned_officer"],
                public_resolution_statement=r["resolution_summary"],
                resolution_notes=r["resolution_summary"],
                resolution_date=res_date,
                resolution_status="Resolved" if r["status"] in ["Disposed", "Resolved", "Closed"] else "Not Yet Resolved",
                routing_reason=r["routing_reason"],
                created_at=created_at,
                updated_at=updated_at,
            )
            db.session.add(new_c)
            db.session.flush()
            comp_map[r["id"]] = new_c.id

        db.session.commit()
        print(f"Migrated complaints. Total mapped: {len(comp_map)}.")

        print("\n=== Step 6: Migrating Overlap Alerts (354 records) ===")
        cur1.execute("SELECT * FROM overlap_alerts")
        overlap_rows = cur1.fetchall()
        migrated_overlaps = 0

        for r in overlap_rows:
            c1_new = comp_map.get(r["complaint_id_1"])
            c2_new = comp_map.get(r["complaint_id_2"])
            if not c1_new or not c2_new:
                continue

            first_id = min(c1_new, c2_new)
            second_id = max(c1_new, c2_new)

            # Check if pair already exists
            existing = db.session.query(OverlapRelationship).filter_by(
                first_complaint_id=first_id,
                second_complaint_id=second_id,
            ).first()
            if existing:
                continue

            # Map status
            status_raw = r["status"]
            decision_raw = r["review_decision"]
            if status_raw == "Confirmed Linked":
                review_status = "Confirmed Related"
                rel_type = "Human-Confirmed Related"
            elif status_raw == "Dismissed False Positive":
                review_status = "Rejected Not Related"
                rel_type = "Human-Confirmed Not Related"
            else:
                review_status = "Pending Review"
                rel_type = "Strong Potential Overlap" if (r["confidence_score"] or 0) >= 0.70 else "Possible Overlap"

            reviewed_at = None
            if r["reviewed_at"]:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        reviewed_at = datetime.strptime(r["reviewed_at"], fmt)
                        break
                    except ValueError:
                        pass

            new_rel = OverlapRelationship(
                first_complaint_id=first_id,
                second_complaint_id=second_id,
                similarity_score=r["confidence_score"] or 0.75,
                relationship_type=rel_type,
                review_status=review_status,
                matching_evidence=r["match_reasons"] or "Matched via AICTE permanent identifier and narrative similarity.",
                review_notes=r["review_remarks"],
                reviewed_at=reviewed_at,
                algorithm_version="SENTRIX SIH26264 Multi-Signal Matching Engine",
            )
            db.session.add(new_rel)
            migrated_overlaps += 1

        db.session.commit()
        print(f"Migrated {migrated_overlaps} overlap relationships.")

        print("\n=== Step 7: Migrating Notifications (995 records) ===")
        cur1.execute("SELECT * FROM notifications")
        notif_rows = cur1.fetchall()
        migrated_notifs = 0

        for r in notif_rows:
            comp_id_new = comp_map.get(r["complaint_id"]) if r["complaint_id"] else None
            notif_date = datetime.utcnow()
            if r["created_at"]:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                    try:
                        notif_date = datetime.strptime(r["created_at"], fmt)
                        break
                    except ValueError:
                        pass

            new_n = Notification(
                type=r["type"] or "GENERAL",
                title=r["title"] or "Notification",
                message=r["message"] or "",
                severity=r["severity"] or "info",
                complaint_id=comp_id_new,
                bureau=r["bureau"],
                is_read=bool(r["is_read"]),
                created_at=notif_date,
                complainant_id=r["complainant_id"],
            )
            db.session.add(new_n)
            migrated_notifs += 1

        db.session.commit()
        print(f"Migrated {migrated_notifs} notifications.")

        print("\n=== Step 8: Migrating Case Actions / Audit Trail (787 records) ===")
        cur1.execute("SELECT * FROM case_actions")
        action_rows = cur1.fetchall()
        migrated_actions = 0

        for r in action_rows:
            comp_id_new = comp_map.get(r["complaint_id"])
            if not comp_id_new:
                continue

            action_date = datetime.utcnow()
            if r["created_at"]:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                    try:
                        action_date = datetime.strptime(r["created_at"], fmt)
                        break
                    except ValueError:
                        pass

            # Record in status history if to_value is present
            if r["to_value"]:
                sh = ComplaintStatusHistory(
                    complaint_id=comp_id_new,
                    previous_status=r["from_value"],
                    new_status=r["to_value"],
                    actor_name=r["actor_name"] or "System",
                    notes=r["remarks"],
                    timestamp=action_date,
                )
                db.session.add(sh)

            # Also log as audit event
            ae = AuditEvent(
                actor_id=None,
                actor_name=r["actor_name"] or "Officer",
                actor_role=r["actor_role"] or "Reviewer",
                action=r["action_type"] or "CASE_ACTION",
                entity_type="Complaint",
                entity_id=str(comp_id_new),
                metadata_json=f'{{"from": "{r["from_value"]}", "to": "{r["to_value"]}", "remarks": "{r["remarks"]}"}}',
                timestamp=action_date,
            )
            db.session.add(ae)
            migrated_actions += 1

        db.session.commit()
        print(f"Migrated {migrated_actions} case actions into audit history.")

        conn1.close()
        print("\n=== MIGRATION SUCCESSFULLY COMPLETED ===")

        # Summary of final counts
        tot_inst = db.session.query(Institution).count()
        tot_user = db.session.query(User).count()
        tot_comp = db.session.query(Complaint).count()
        tot_over = db.session.query(OverlapRelationship).count()
        tot_notif = db.session.query(Notification).count()
        tot_audit = db.session.query(AuditEvent).count()
        tot_sh = db.session.query(ComplaintStatusHistory).count()
        print(f"Final Totals in aicte_monitoring.db:")
        print(f"  Institutions: {tot_inst}")
        print(f"  Users:        {tot_user}")
        print(f"  Complaints:   {tot_comp}")
        print(f"  Overlaps:     {tot_over}")
        print(f"  Notifications:{tot_notif}")
        print(f"  Audit Events: {tot_audit}")
        print(f"  Status Logs:  {tot_sh}")


if __name__ == "__main__":
    run_migration()
