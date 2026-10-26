from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import func, case
from models.complaint import Complaint
from models.institution import Institution
from models.overlap import OverlapRelationship
from models.user import User


def get_dashboard_metrics(
    session,
    institution_id: Optional[int] = None,
    category: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict:
    """Calculates all key administrative monitoring metrics live from the database."""
    query = session.query(Complaint)

    if institution_id:
        query = query.filter(Complaint.institution_id == institution_id)
    if category:
        query = query.filter(Complaint.category == category)
    if start_date:
        query = query.filter(Complaint.created_at >= start_date)
    if end_date:
        query = query.filter(Complaint.created_at <= end_date)

    all_complaints = query.all()
    total_complaints = len(all_complaints)

    open_complaints = sum(1 for c in all_complaints if c.status == "Open")
    under_review = sum(1 for c in all_complaints if c.status in ["Under Review", "Under Investigation"])
    pending_count = sum(1 for c in all_complaints if c.status == "Pending")
    escalated = sum(1 for c in all_complaints if c.status == "Escalated")
    resolved = sum(1 for c in all_complaints if c.status in ["Resolved", "Closed"])

    # Overdue threshold: 30 days
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    overdue_count = sum(
        1 for c in all_complaints
        if c.status in ["Open", "Under Review", "Under Investigation", "Pending", "Escalated"] and c.created_at and c.created_at < thirty_days_ago
    )

    # Overlaps awaiting review
    overlap_query = session.query(OverlapRelationship).filter(OverlapRelationship.review_status == "Pending Review")
    if institution_id:
        # Overlaps involving complaints from this institution
        inst_c_ids = [c.id for c in all_complaints]
        overlap_query = overlap_query.filter(
            (OverlapRelationship.first_complaint_id.in_(inst_c_ids)) |
            (OverlapRelationship.second_complaint_id.in_(inst_c_ids))
        )

    pending_overlaps = overlap_query.all()
    strong_overlaps_pending = sum(1 for o in pending_overlaps if o.relationship_type == "Strong Potential Overlap")
    possible_overlaps_pending = sum(1 for o in pending_overlaps if o.relationship_type == "Possible Overlap")

    # Status distribution for charts
    status_counts = {"Open": 0, "Under Investigation": 0, "Pending": 0, "Under Review": 0, "Escalated": 0, "Resolved": 0, "Closed": 0}
    for c in all_complaints:
        if c.status in status_counts:
            status_counts[c.status] += 1
        else:
            status_counts[c.status] = 1

    # Priority distribution
    priority_counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    for c in all_complaints:
        if c.priority in priority_counts:
            priority_counts[c.priority] += 1
        else:
            priority_counts[c.priority] = 1

    # Category distribution
    category_counts = {}
    for c in all_complaints:
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    # Monthly trends (past 6 months)
    trend_labels = []
    trend_counts = []
    for i in range(5, -1, -1):
        target_month = now.replace(day=1) - timedelta(days=i * 28)
        month_label = target_month.strftime("%b %Y")
        trend_labels.append(month_label)
        count = sum(
            1 for c in all_complaints
            if c.created_at and c.created_at.year == target_month.year and c.created_at.month == target_month.month
        )
        trend_counts.append(count)

    # Top institutions with complaints
    inst_counts_query = (
        session.query(Institution.name, func.count(Complaint.id).label("total"))
        .join(Complaint, Institution.id == Complaint.institution_id)
        .group_by(Institution.id)
        .order_by(func.count(Complaint.id).desc())
        .limit(5)
        .all()
    )
    top_institutions = [{"name": name, "count": count} for name, count in inst_counts_query]

    # Average resolution time in days
    resolved_times = [
        (c.resolution_date - c.created_at).total_seconds() / 86400.0
        for c in all_complaints
        if c.resolution_date and c.created_at and c.resolution_date >= c.created_at
    ]
    avg_resolution_days = round(sum(resolved_times) / len(resolved_times), 1) if resolved_times else 0.0

    # Extended SENTRIX SIH26264 Bureau & SLA Metrics
    bureau_distribution = {}
    for c in all_complaints:
        b = c.source_bureau or "PGRC (Public Grievance Redressal)"
        bureau_distribution[b] = bureau_distribution.get(b, 0) + 1

    bureau_sla_breakdown = []
    for b_name in [
        "PGRC (Public Grievance Redressal)",
        "Regulation Bureau (RB)",
        "Approval Bureau (AB)",
        "Policy & Academic Planning Bureau (PAPB)",
        "Anti-Ragging Cell (ARC)",
        "Skill Development Cell (SDC)",
    ]:
        b_cases = [c for c in all_complaints if c.source_bureau == b_name]
        b_tot = len(b_cases)
        if b_tot > 0:
            b_overdue = sum(1 for c in b_cases if c.is_overdue)
            b_on_track = max(0, b_tot - b_overdue)
            b_comp_rate = round((b_on_track / b_tot) * 100, 1)
            bureau_sla_breakdown.append({
                "bureau": b_name,
                "total": b_tot,
                "on_track": b_on_track,
                "overdue": b_overdue,
                "compliance_pct": b_comp_rate,
            })

    # Intake vs Resolved 6-month comparison
    intake_vs_resolved = {"labels": trend_labels, "intake": trend_counts, "resolved": []}
    for i in range(5, -1, -1):
        target_month = now.replace(day=1) - timedelta(days=i * 28)
        res_count = sum(
            1 for c in all_complaints
            if c.resolution_date and c.resolution_date.year == target_month.year and c.resolution_date.month == target_month.month
        )
        intake_vs_resolved["resolved"].append(res_count)

    sla_compliance_rate = round(max(0.0, (total_complaints - overdue_count) / max(1, total_complaints)) * 100, 1)

    return {
        "total_complaints": total_complaints,
        "open_complaints": open_complaints,
        "under_review_complaints": under_review,
        "under_process_complaints": max(0, total_complaints - resolved),
        "pending_complaints": pending_count,
        "escalated_complaints": escalated,
        "resolved_complaints": resolved,
        "overdue_complaints": overdue_count,
        "sla_compliance_rate": sla_compliance_rate,
        "strong_overlaps_pending": strong_overlaps_pending,
        "possible_overlaps_pending": possible_overlaps_pending,
        "status_distribution": status_counts,
        "priority_distribution": priority_counts,
        "category_distribution": category_counts,
        "bureau_distribution": bureau_distribution,
        "bureau_sla_breakdown": bureau_sla_breakdown,
        "intake_vs_resolved": intake_vs_resolved,
        "trend_labels": trend_labels,
        "trend_counts": trend_counts,
        "top_institutions": top_institutions,
        "avg_resolution_days": avg_resolution_days,
    }


def get_overlap_review_analytics(session) -> Dict:
    """Calculates statistics on human review actions vs algorithmic detections."""
    all_overlaps = session.query(OverlapRelationship).all()
    total = len(all_overlaps)

    pending = sum(1 for o in all_overlaps if o.review_status == "Pending Review")
    confirmed = sum(1 for o in all_overlaps if o.review_status == "Confirmed Related")
    rejected = sum(1 for o in all_overlaps if o.review_status == "Rejected Not Related")

    strong_total = sum(1 for o in all_overlaps if o.relationship_type == "Strong Potential Overlap")
    possible_total = sum(1 for o in all_overlaps if o.relationship_type == "Possible Overlap")

    # Accuracy / acceptance rate of algorithmic recommendations
    reviewed_count = confirmed + rejected
    acceptance_rate = round((confirmed / reviewed_count * 100), 1) if reviewed_count > 0 else 0.0

    return {
        "total_overlaps": total,
        "pending_review": pending,
        "confirmed_related": confirmed,
        "rejected_not_related": rejected,
        "strong_potential_total": strong_total,
        "possible_overlap_total": possible_total,
        "acceptance_rate": acceptance_rate,
        "reviewed_count": reviewed_count,
    }


def get_overlap_trends(session, institution_id: Optional[int] = None) -> Dict:
    """Computes strong vs possible overlap counts over time based on complaint submission dates."""
    now = datetime.utcnow()
    # 6 bi-weekly periods spanning past 90 days
    intervals = []
    labels = []
    for i in range(5, -1, -1):
        start = now - timedelta(days=(i + 1) * 15)
        end = now - timedelta(days=i * 15)
        label = f"{start.strftime('%d %b')} - {end.strftime('%d %b')}"
        intervals.append((start, end))
        labels.append(label)

    strong_counts = [0] * len(intervals)
    possible_counts = [0] * len(intervals)

    query = session.query(OverlapRelationship)
    if institution_id:
        query = query.filter(
            (OverlapRelationship.first_complaint.has(institution_id=institution_id)) |
            (OverlapRelationship.second_complaint.has(institution_id=institution_id))
        )
    overlaps = query.all()

    for o in overlaps:
        if o.review_status == "Rejected Not Related":
            continue
        # Use later complaint submission date as the emergence date of the overlap
        dt = max(
            o.first_complaint.created_at if o.first_complaint and o.first_complaint.created_at else now,
            o.second_complaint.created_at if o.second_complaint and o.second_complaint.created_at else now,
        )
        is_strong = (o.similarity_score >= 0.80 or o.relationship_type == "Strong Potential Overlap")

        for idx, (start, end) in enumerate(intervals):
            if start <= dt <= end:
                if is_strong:
                    strong_counts[idx] += 1
                else:
                    possible_counts[idx] += 1
                break

    return {
        "labels": labels,
        "strong_counts": strong_counts,
        "possible_counts": possible_counts,
    }


def get_overlap_network_graph(session, institution_id: Optional[int] = None) -> Dict:
    """Produces node-link relationship graph data for interactive canvas visualization."""
    comp_query = session.query(Complaint)
    if institution_id:
        comp_query = comp_query.filter(Complaint.institution_id == institution_id)
    complaints = comp_query.all()
    complaint_ids = {c.id for c in complaints}

    overlap_query = session.query(OverlapRelationship).filter(
        OverlapRelationship.similarity_score >= 0.50,
        OverlapRelationship.review_status != "Rejected Not Related",
    )
    if institution_id:
        overlap_query = overlap_query.filter(
            (OverlapRelationship.first_complaint_id.in_(complaint_ids)) |
            (OverlapRelationship.second_complaint_id.in_(complaint_ids))
        )
    overlaps = overlap_query.all()

    # Collect all complaints that are actually part of the visible set or connected edges
    connected_ids = set()
    for o in overlaps:
        connected_ids.add(o.first_complaint_id)
        connected_ids.add(o.second_complaint_id)

    # If filtering, include all complaints or those connected
    target_complaints = complaints if len(complaints) <= 40 else [c for c in complaints if c.id in connected_ids]

    nodes = []
    for c in target_complaints:
        nodes.append({
            "id": c.id,
            "ref": c.reference_number,
            "title": c.title,
            "category": c.category,
            "status": c.status,
            "priority": c.priority,
            "institution_id": c.institution_id,
            "institution_name": c.institution.name if c.institution else "Unknown",
            "institution_code": c.institution.code if c.institution else "",
            "is_confidential": c.is_confidential,
            "date": c.created_at.strftime("%d %b %Y") if c.created_at else "",
            "has_connections": (c.id in connected_ids),
        })

    edges = []
    node_id_set = {n["id"] for n in nodes}
    for o in overlaps:
        if o.first_complaint_id in node_id_set and o.second_complaint_id in node_id_set:
            same_inst = (
                o.first_complaint.institution_id == o.second_complaint.institution_id
                if o.first_complaint and o.second_complaint else False
            )
            is_strong = (o.similarity_score >= 0.80 or o.relationship_type == "Strong Potential Overlap")
            edges.append({
                "id": o.id,
                "source": o.first_complaint_id,
                "target": o.second_complaint_id,
                "similarity_score": round(o.similarity_score, 4),
                "similarity_pct": round(o.similarity_score * 100, 1),
                "relationship_type": o.relationship_type,
                "is_strong": is_strong,
                "same_institution": same_inst,
                "review_status": o.review_status,
                "source_ref": o.first_complaint.reference_number if o.first_complaint else "",
                "target_ref": o.second_complaint.reference_number if o.second_complaint else "",
                "source_title": o.first_complaint.title if o.first_complaint else "",
                "target_title": o.second_complaint.title if o.second_complaint else "",
                "source_inst": o.first_complaint.institution.name if o.first_complaint and o.first_complaint.institution else "",
                "target_inst": o.second_complaint.institution.name if o.second_complaint and o.second_complaint.institution else "",
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }


def get_institution_overlap_comparison(session) -> Dict:
    """Compares strong and possible overlaps per institution, separating same-institution vs cross-institution."""
    institutions = session.query(Institution).order_by(Institution.name).all()
    labels = []
    same_strong = []
    same_possible = []
    cross_strong = []
    cross_possible = []

    for inst in institutions:
        labels.append(inst.code)
        # All active overlaps involving this institution
        overlaps = session.query(OverlapRelationship).filter(
            OverlapRelationship.similarity_score >= 0.50,
            OverlapRelationship.review_status != "Rejected Not Related",
            (
                (OverlapRelationship.first_complaint.has(institution_id=inst.id)) |
                (OverlapRelationship.second_complaint.has(institution_id=inst.id))
            )
        ).all()

        ss = 0
        sp = 0
        cs = 0
        cp = 0

        for o in overlaps:
            is_same = (
                o.first_complaint.institution_id == o.second_complaint.institution_id
                if o.first_complaint and o.second_complaint else False
            )
            is_strong = (o.similarity_score >= 0.80 or o.relationship_type == "Strong Potential Overlap")

            if is_same:
                if is_strong:
                    ss += 1
                else:
                    sp += 1
            else:
                if is_strong:
                    cs += 1
                else:
                    cp += 1

        same_strong.append(ss)
        same_possible.append(sp)
        cross_strong.append(cs)
        cross_possible.append(cp)

    return {
        "labels": labels,
        "same_strong": same_strong,
        "same_possible": same_possible,
        "cross_strong": cross_strong,
        "cross_possible": cross_possible,
    }


def get_category_overlap_analysis(session, institution_id: Optional[int] = None) -> Dict:
    """Computes overlap frequency by complaint category."""
    query = session.query(OverlapRelationship).filter(
        OverlapRelationship.similarity_score >= 0.50,
        OverlapRelationship.review_status != "Rejected Not Related",
    )
    if institution_id:
        query = query.filter(
            (OverlapRelationship.first_complaint.has(institution_id=institution_id)) |
            (OverlapRelationship.second_complaint.has(institution_id=institution_id))
        )
    overlaps = query.all()

    category_stats: Dict[str, Dict[str, int]] = {}
    for o in overlaps:
        c1 = o.first_complaint
        c2 = o.second_complaint
        if not c1 or not c2:
            continue
        is_strong = (o.similarity_score >= 0.80 or o.relationship_type == "Strong Potential Overlap")

        # Attribute overlap involvement to both complaints' categories
        cats = {c1.category, c2.category}
        for cat in cats:
            if cat not in category_stats:
                category_stats[cat] = {"strong": 0, "possible": 0, "total": 0}
            if is_strong:
                category_stats[cat]["strong"] += 1
            else:
                category_stats[cat]["possible"] += 1
            category_stats[cat]["total"] += 1

    # Sort categories by total overlap involvements descending
    sorted_cats = sorted(category_stats.items(), key=lambda x: x[1]["total"], reverse=True)
    labels = [k for k, v in sorted_cats]
    strong_data = [v["strong"] for k, v in sorted_cats]
    possible_data = [v["possible"] for k, v in sorted_cats]

    return {
        "labels": labels,
        "strong": strong_data,
        "possible": possible_data,
    }


def get_recurrence_analysis(session, institution_id: Optional[int] = None) -> Dict:
    """Analyzes resolved complaints vs subsequent re-emergence of identical or related issues."""
    resolved_query = session.query(Complaint).filter(Complaint.status.in_(["Resolved", "Closed"]))
    if institution_id:
        resolved_query = resolved_query.filter(Complaint.institution_id == institution_id)
    resolved_complaints = resolved_query.all()
    total_resolved = len(resolved_complaints)

    suspected_count = 0
    confirmed_count = 0
    recurrence_items = []
    affected_resolved_ids = set()

    for r in resolved_complaints:
        # Check all overlaps where this complaint is involved
        for o in r.all_overlaps:
            if o.review_status == "Rejected Not Related" or o.similarity_score < 0.50:
                continue

            other = o.second_complaint if o.first_complaint_id == r.id else o.first_complaint
            if not other:
                continue

            # A recurrence is when the other complaint was submitted AFTER the resolved complaint
            # or after its resolution_date
            r_dt = r.resolution_date or r.created_at
            if other.created_at and r_dt and other.created_at > r_dt:
                affected_resolved_ids.add(r.id)
                is_confirmed = (o.review_status == "Confirmed Related")
                if is_confirmed:
                    confirmed_count += 1
                    rec_type = "Confirmed Recurrence"
                else:
                    suspected_count += 1
                    rec_type = "Suspected Recurrence"

                days_elapsed = abs((other.created_at - r_dt).days)
                recurrence_items.append({
                    "resolved_id": r.id,
                    "resolved_ref": r.reference_number,
                    "resolved_title": r.title,
                    "resolution_notes": r.resolution_notes or "Marked resolved by administrative officer.",
                    "resolved_date": r_dt.strftime("%d %b %Y"),
                    "recurring_id": other.id,
                    "recurring_ref": other.reference_number,
                    "recurring_title": other.title,
                    "recurring_status": other.status,
                    "recurring_date": other.created_at.strftime("%d %b %Y"),
                    "institution_name": r.institution.name if r.institution else "Unknown",
                    "similarity_score": round(o.similarity_score * 100, 1),
                    "recurrence_type": rec_type,
                    "days_elapsed": days_elapsed,
                    "overlap_id": o.id,
                })

    clean_resolved = max(0, total_resolved - len(affected_resolved_ids))

    return {
        "total_resolved": total_resolved,
        "clean_resolved": clean_resolved,
        "suspected_count": suspected_count,
        "confirmed_count": confirmed_count,
        "recurrence_items": recurrence_items,
    }
