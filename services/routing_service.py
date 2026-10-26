import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("aicte-routing")

# Destination Constants
DEST_PGRC = "PGRC"
DEST_RB = "RB"
DEST_AB = "AB"
DEST_PAPB = "PAPB"
DEST_FB = "FB"
DEST_ARC = "ARC"
DEST_SDC = "SDC"
DEST_RC = "RC"
DEST_INSTITUTIONAL = "Institutional Reviewer"
DEST_MANUAL = "Manual Review"

ALL_DESTINATIONS = [
    DEST_PGRC,
    DEST_RB,
    DEST_AB,
    DEST_PAPB,
    DEST_FB,
    DEST_ARC,
    DEST_SDC,
    DEST_RC,
    DEST_INSTITUTIONAL,
    DEST_MANUAL,
]
VALID_DESTINATIONS = ALL_DESTINATIONS

BUREAU_MAP = {
    "PGRC": "PGRC (Public Grievance Redressal)",
    "RB": "Regulation Bureau (RB)",
    "AB": "Approval Bureau (AB)",
    "PAPB": "Policy & Academic Planning Bureau (PAPB)",
    "FB": "Finance Bureau (FB)",
    "ARC": "Anti-Ragging Cell (ARC)",
    "SDC": "Skill Development Cell (SDC)",
    "RC": "Regional Committee (RC Compliance)",
    "Institutional Reviewer": "Institutional Tier",
    "Manual Review": "Manual / Triage",
}

# Domain Keyword Taxonomies
PGRC_KEYWORDS = [
    "ragging", "harassment", "harass", "bully", "discriminate", "discrimination",
    "caste", "gender", "scholarship", "delayed scholarship", "fees", "fee irregular",
    "capitation", "overcharge", "refund", "faculty misconduct", "abusive teacher",
    "sexual harassment", "mental harassment", "threat", "victimization", "marks deduction",
    "arbitrary marks", "attendance extortion", "student council", "victim", "assault"
]

RC_KEYWORDS = [
    "approval", "affiliation", "aph", "approval process handbook", "intake violation",
    "excess intake", "unapproved course", "unapproved branch", "unapproved campus",
    "land deficiency", "built-up area", "fire safety certificate", "building safety",
    "deficiency", "regulatory inspection", "compliance discrepancy", "forged documents",
    "fake faculty", "statutory norm", "council directive", "accreditation fraud"
]

INSTITUTIONAL_KEYWORDS = [
    "laboratory", "lab equipment", "tensile machine", "computer monitor", "workshop",
    "hostel", "mess food", "canteen", "drinking water", "water cooler", "sanitation",
    "washroom", "cleanliness", "broken bench", "library", "wifi", "internet connection",
    "projector", "air conditioner", "campus lighting", "water supply", "damaged pipe"
]


def suggest_department_routing(
    title: str,
    description: str,
    category: Optional[str] = None,
    institution_name: Optional[str] = None,
    allow_semantic: bool = True
) -> Dict[str, Any]:
    """
    AI-Assisted Department Routing Classifier.
    Evaluates grievance text, category taxonomy, and institutional context to
    suggest the appropriate authority (PGRC, RC, Institutional Reviewer, or Manual Review).

    Advisory only: Always flags `requires_human_review = True` for human confirmation.
    """
    combined_text = f"{title} {description}".lower()
    cat = (category or "").strip()

    # Score counters
    pgrc_score = 0.0
    rc_score = 0.0
    inst_score = 0.0

    # 1. Primary Category Taxonomy Weighting
    if cat in [
        "Ragging and Student Harassment",
        "Discrimination and Student Welfare",
        "Financial Issues and Fee Irregularities",
        "Scholarship Delays",
        "Faculty Misconduct",
    ]:
        pgrc_score += 0.55
    elif cat in ["Academic and Examination Issues"]:
        pgrc_score += 0.40
    elif cat in [
        "Laboratory Equipment and Infrastructure",
        "Hostel and Accommodation",
        "Sanitation and Drinking Water",
        "Library and Learning Resources",
        "Safety and Security"
    ]:
        inst_score += 0.45
    elif cat in ["Other"]:
        # ambiguous
        pass

    # 2. Domain Keyword Matching
    for kw in PGRC_KEYWORDS:
        if kw in combined_text:
            pgrc_score += 0.15

    for kw in RC_KEYWORDS:
        if kw in combined_text:
            rc_score += 0.25

    for kw in INSTITUTIONAL_KEYWORDS:
        if kw in combined_text:
            inst_score += 0.15

    # Check for direct statutory/regulatory violations (RC triggers)
    has_rc_trigger = any(term in combined_text for term in [
        "approval process", "intake violation", "unapproved", "land deficiency",
        "inspection report", "affiliation", "statutory norm", "regulatory compliance"
    ])
    if has_rc_trigger:
        rc_score += 0.40

    # Determine Destination Recommendation
    scores = {
        DEST_PGRC: pgrc_score,
        DEST_RC: rc_score,
        DEST_INSTITUTIONAL: inst_score,
    }
    top_dest, top_score = max(scores.items(), key=lambda item: item[1])

    # Normalization & Confidence
    confidence = min(0.96, max(0.50, round(0.50 + (top_score * 0.45), 2)))

    # Fallback to Manual Review if ambiguous or very low score
    if top_score < 0.25 or (cat == "Other" and top_score < 0.35):
        fallback_reason = "Grievance text spans multiple domains or lacks definitive taxonomy markers. Assigned for authorized human officer triage."
        return {
            "suggested_destination": DEST_MANUAL,
            "reason": fallback_reason,
            "routing_reason": fallback_reason,
            "relevant_category": cat or "General",
            "confidence_score": round(max(0.40, confidence * 0.7), 2),
            "requires_human_review": True,
            "rule_matched": "MANUAL_TRIAGE_AMBIGUOUS",
        }

    # Construct Informative Routing Justification
    if top_dest == DEST_PGRC:
        reason = (
            "Grievance concerns student welfare, financial irregularities, anti-ragging protections, "
            "or faculty conduct, which falls under the purview of the Public Grievance Redressal Committee (PGRC)."
        )
        rule = "PGRC_STUDENT_WELFARE_MANDATE"
    elif top_dest == DEST_RC:
        reason = (
            "Grievance indicates statutory norm non-compliance, approval handbook deviations, or regulatory inspection "
            "deficiencies within the Regional Committee's (RC) administrative oversight remit."
        )
        rule = "RC_REGULATORY_COMPLIANCE_REMIT"
    else:
        reason = (
            "Grievance relates to campus-level operational infrastructure, laboratory equipment maintenance, "
            "or hostel amenities, which should first be addressed and rectified at the institutional tier."
        )
        rule = "INSTITUTIONAL_LOCAL_FACILITY_MAINTENANCE"

    return {
        "suggested_destination": top_dest,
        "reason": reason,
        "routing_reason": reason,
        "relevant_category": cat or "General",
        "confidence_score": confidence,
        "requires_human_review": True,
        "rule_matched": rule,
    }
