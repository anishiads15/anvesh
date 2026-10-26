import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from models.complaint import Complaint
from models.overlap import OverlapRelationship
from services.categorization import _get_transformer_model, extract_keywords, normalize_token

logger = logging.getLogger(__name__)

# Known facility/sub-domain markers
FACILITY_MARKERS = [
    r"\bmechanical\s+(?:engineering\s+|department'?s?\s+)?lab\w*\b",
    r"\belectrical\s+(?:engineering\s+|department'?s?\s+)?lab\w*\b",
    r"\bcomputer\s+(?:science\s+|department'?s?\s+)?lab\w*\b",
    r"\bchemistry\s+lab\w*\b",
    r"\bphysics\s+lab\w*\b",
    r"\bcivil\s+lab\w*\b",
    r"\bclassroom\s+\d+\b",
    r"\bhostel(?:\s+block|\s+wing)?\s+[a-zA-Z0-9]+\b",
    r"\b(?:boys|girls)\s+hostel(?:\s+wing|\s+block)?\s+[a-zA-Z0-9]+\b",
    r"\blibrary\b",
    r"\bhostel\b",
    r"\bmess\b",
    r"\bcanteen\b",
    r"\bsports\s+ground\b",
    r"\bgym\b",
    r"\bdrinking\s+water\b",
    r"\bwater\s+purifier\b",
    r"\bwashroom\b",
    r"\btoilet\b",
    r"\bmain\s+auditorium\b",
    r"\bworkshop\b",
]

# Explicit contradictory topic signatures that should heavily suppress overlap flags
CONTRADICTORY_TOPIC_PAIRS = [
    ({"drinking water", "purifier", "washroom", "toilet", "sanitation", "sewage"},
     {"lab", "laboratory", "apparatus", "equipment", "machine", "machinery", "practical", "lathe"}),
    ({"ragging", "harassment", "bully"},
     {"wifi", "internet", "canteen", "library", "books"}),
    ({"fee", "refund", "scholarship", "tuition"},
     {"hostel", "washroom", "drinking water", "laboratory", "workshop"}),
]


def normalize_facility_name(fac: str) -> str:
    """Normalizes facility strings into canonical campus locations."""
    f = fac.lower()
    if "mechanical" in f and "lab" in f:
        return "mechanical lab"
    if "electrical" in f and "lab" in f:
        return "electrical lab"
    if "computer" in f and "lab" in f:
        return "computer lab"
    if "classroom" in f:
        nums = re.findall(r"\d+", f)
        return f"classroom {nums[0]}" if nums else "classroom"
    if "hostel" in f:
        tokens = re.findall(r"\b[a-zA-Z0-9]\b", f)
        return f"hostel block {tokens[-1].upper()}" if tokens else "hostel"
    return f


def extract_facilities(text: str) -> List[str]:
    """Finds named facilities or specialized locations mentioned in the complaint."""
    found = []
    text_lower = text.lower()
    for pattern in FACILITY_MARKERS:
        match = re.search(pattern, text_lower)
        if match:
            found.append(normalize_facility_name(match.group(0).strip()))
    return list(set(found))


def compute_keyword_similarity(kw1: List[str], kw2: List[str]) -> Tuple[float, List[str]]:
    """Calculates Sorensen-Dice keyword similarity using normalized tokens."""
    set1 = set(normalize_token(w) for w in kw1)
    set2 = set(normalize_token(w) for w in kw2)
    if not set1 or not set2:
        return 0.0, []

    shared = list(set1.intersection(set2))
    score = (2.0 * len(shared)) / (len(set1) + len(set2))
    return min(1.0, max(0.0, score)), shared


def compute_semantic_similarity(
    text1: str,
    text2: str,
    allow_transformer: bool = True
) -> Tuple[float, str]:
    """Computes semantic similarity between two texts using SentenceTransformer
    or falls back to multi-granular (character-ngram + word-ngram) TF-IDF cosine similarity.
    """
    model = _get_transformer_model() if allow_transformer else None

    if model is not None:
        try:
            embeddings = model.encode([text1, text2])
            sim = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
            normalized_sim = max(0.0, min(1.0, sim))
            return normalized_sim, "Sentence Transformers (all-MiniLM-L6-v2)"
        except Exception as e:
            logger.warning(f"Error computing SentenceTransformer embeddings: {e}. Falling back to TF-IDF.")

    # High-recall TF-IDF fallback leveraging character n-grams and word n-grams
    try:
        char_vec = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            sublinear_tf=True,
        )
        char_matrix = char_vec.fit_transform([text1, text2])
        char_sim = float(cosine_similarity(char_matrix[0:1], char_matrix[1:2])[0][0])

        word_vec = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
        )
        word_matrix = word_vec.fit_transform([text1, text2])
        word_sim = float(cosine_similarity(word_matrix[0:1], word_matrix[1:2])[0][0])

        # Morphological character n-grams bridge variations like machine/machinery and lab/laboratory
        blended_sim = (0.65 * char_sim) + (0.35 * word_sim)
        return max(0.0, min(1.0, blended_sim)), "TF-IDF Morphological N-gram Cosine (Fallback)"
    except Exception as e:
        logger.error(f"Error computing TF-IDF similarity: {e}")
        return 0.0, "Error / Zero Cosine"


def compute_category_compatibility(cat1: str, cat2: str) -> float:
    """Returns category compatibility score between 0.0 and 1.0."""
    if not cat1 or not cat2:
        return 0.5
    if cat1.lower() == cat2.lower():
        return 1.0

    COMPATIBLE_PAIRS = [
        ({"laboratory and equipment", "academic quality"}, 0.40),
        ({"infrastructure", "safety and accessibility"}, 0.45),
        ({"student facilities", "infrastructure"}, 0.35),
        ({"faculty and staffing", "academic quality"}, 0.45),
        ({"laboratory equipment and infrastructure", "academic and examination issues"}, 0.40),
        ({"hostel and accommodation", "sanitation and drinking water"}, 0.40),
        ({"hostel and accommodation", "safety and security"}, 0.35),
        ({"faculty misconduct", "academic and examination issues"}, 0.45),
        ({"financial issues and fee irregularities", "scholarship delays"}, 0.45),
        ({"ragging and student harassment", "safety and security"}, 0.40),
        ({"discrimination and student welfare", "ragging and student harassment"}, 0.35),
        ({"library and learning resources", "academic and examination issues"}, 0.40),
        # Cross-compatibility between old and new labels
        ({"laboratory equipment and infrastructure", "laboratory and equipment"}, 1.0),
        ({"sanitation and drinking water", "infrastructure"}, 0.80),
        ({"faculty misconduct", "faculty and staffing"}, 0.85),
    ]

    c1, c2 = cat1.lower(), cat2.lower()
    for pair, score in COMPATIBLE_PAIRS:
        if c1 in pair and c2 in pair:
            return score

    return 0.0


def compute_context_similarity(
    c1: Complaint,
    c2: Complaint,
    facilities1: List[str],
    facilities2: List[str]
) -> Tuple[float, dict]:
    """Evaluates contextual signals: institution identity, physical facility matches, and temporal proximity.
    CRITICAL: Shared physical facilities only apply when complaints share the same institution.
    """
    score = 0.0
    evidence = {}

    same_inst = (c1.institution_id == c2.institution_id)
    evidence["same_institution"] = same_inst

    if same_inst:
        score += 0.50
        # Physical facility matches within the SAME campus
        shared_fac = list(set(facilities1).intersection(set(facilities2)))
        evidence["shared_facilities"] = shared_fac
        if shared_fac:
            score += 0.30
    else:
        # Different institutions cannot share the same physical laboratory or classroom
        evidence["shared_facilities"] = []

    # Temporal proximity
    days_diff = None
    if c1.created_at and c2.created_at:
        days_diff = abs((c1.created_at - c2.created_at).days)
        evidence["days_apart"] = days_diff
        if days_diff <= 45:
            score += 0.20
        elif days_diff <= 90:
            score += 0.10
    else:
        score += 0.10

    return min(1.0, score), evidence


def check_contradictory_topics(text1: str, text2: str) -> Optional[str]:
    """Detects whether two complaints are manifestly discussing unrelated/contradictory subjects."""
    t1_lower = text1.lower()
    t2_lower = text2.lower()

    for set_a, set_b in CONTRADICTORY_TOPIC_PAIRS:
        has_a1 = any(kw in t1_lower for kw in set_a)
        has_b1 = any(kw in t1_lower for kw in set_b)
        has_a2 = any(kw in t2_lower for kw in set_a)
        has_b2 = any(kw in t2_lower for kw in set_b)

        if (has_a1 and not has_b1) and (has_b2 and not has_a2):
            return "Contradictory topics: one complaint focuses on facilities/sanitation while the other focuses on laboratory machinery/equipment."
        if (has_b1 and not has_a1) and (has_a2 and not has_b2):
            return "Contradictory topics: one complaint focuses on facilities/sanitation while the other focuses on laboratory machinery/equipment."

    return None


def calculate_overlap_score(
    c1: Complaint,
    c2: Complaint,
    allow_transformer: bool = True
) -> Dict:
    """Executes the complete multi-signal overlap detection pipeline for a pair of complaints."""
    text1 = f"{c1.title}. {c1.description}"
    text2 = f"{c2.title}. {c2.description}"

    # 1. Semantic Text Similarity (55%)
    sem_score, method_name = compute_semantic_similarity(text1, text2, allow_transformer=allow_transformer)

    # 2. Shared Issue Keywords (20%)
    kw1 = extract_keywords(text1, top_k=8)
    kw2 = extract_keywords(text2, top_k=8)
    kw_score, shared_keywords = compute_keyword_similarity(kw1, kw2)

    # 3. Category Compatibility (15%)
    cat_score = compute_category_compatibility(c1.category, c2.category)

    # 4. Contextual Similarity (10%)
    fac1 = extract_facilities(text1)
    fac2 = extract_facilities(text2)
    ctx_score, ctx_details = compute_context_similarity(c1, c2, fac1, fac2)

    # Composite weighted score
    composite_score = (
        (0.55 * sem_score) +
        (0.20 * kw_score) +
        (0.15 * cat_score) +
        (0.10 * ctx_score)
    )

    # Physical facility match bonus within same campus (identical lab, room, or wing)
    if ctx_details.get("same_institution") and ctx_details.get("shared_facilities"):
        composite_score = min(1.0, composite_score + 0.15)

    # Contradictory evidence filter
    conflicting_reason = check_contradictory_topics(text1, text2)
    if conflicting_reason:
        composite_score = min(composite_score, 0.30)

    # If categories are incompatible and not same institution, cap score
    if cat_score == 0.0 and not ctx_details.get("same_institution"):
        composite_score = min(composite_score, 0.35)

    composite_score = round(max(0.0, min(1.0, composite_score)), 4)

    # Threshold evaluation
    if composite_score >= 0.80:
        rel_type = "Strong Potential Overlap"
        explanation = (
            f"Both complaints demonstrate high semantic alignment ({sem_score:.2f}) and share key operational terms "
            f"[{', '.join(shared_keywords) if shared_keywords else 'contextual terms'}]. "
            f"{'Both originate from the same institution. ' if ctx_details.get('same_institution') else 'Cross-institutional similarity detected. '}"
            f"Strongly recommended for deduplication and consolidation review."
        )
    elif composite_score >= 0.50:
        rel_type = "Possible Overlap"
        explanation = (
            f"Complaints exhibit notable contextual overlap (score: {composite_score:.2f}). "
            f"Keywords in common: [{', '.join(shared_keywords) if shared_keywords else 'thematic alignment'}]. "
            f"Human administrative inspection recommended to verify if they refer to the same incident or grievance."
        )
    else:
        rel_type = "No Overlap"
        explanation = "Insufficient textual or contextual correlation to suggest duplicate grievance."

    evidence = {
        "summary": explanation,
        "shared_keywords": shared_keywords,
        "shared_facilities": ctx_details.get("shared_facilities", []),
        "same_institution": ctx_details.get("same_institution", False),
        "days_apart": ctx_details.get("days_apart"),
        "method": method_name,
        "breakdown": {
            "semantic_text_similarity": round(sem_score, 4),
            "keyword_overlap_similarity": round(kw_score, 4),
            "category_compatibility": round(cat_score, 4),
            "contextual_similarity": round(ctx_score, 4),
        },
    }

    return {
        "similarity_score": composite_score,
        "semantic_score": sem_score,
        "keyword_score": kw_score,
        "category_score": cat_score,
        "context_score": ctx_score,
        "relationship_type": rel_type,
        "matching_evidence": json.dumps(evidence),
        "conflicting_evidence": conflicting_reason,
        "algorithm_version": f"v2.1-hybrid ({method_name})",
        "evidence_dict": evidence,
    }


def evaluate_complaint_against_all(
    new_complaint: Complaint,
    session,
    allow_transformer: bool = True,
    auto_save: bool = True
) -> List[OverlapRelationship]:
    """Compares a complaint against all other eligible complaints in the database,
    storing canonical pairs for all strong and possible overlaps.
    """
    other_complaints = session.query(Complaint).filter(Complaint.id != new_complaint.id).all()
    detected_relationships = []

    for other in other_complaints:
        # Canonical ordering: first_id < second_id
        first_c = new_complaint if new_complaint.id < other.id else other
        second_c = other if new_complaint.id < other.id else new_complaint

        existing = session.query(OverlapRelationship).filter_by(
            first_complaint_id=first_c.id,
            second_complaint_id=second_c.id
        ).first()

        if existing and existing.review_status in ["Confirmed Related", "Rejected Not Related"]:
            continue

        result = calculate_overlap_score(first_c, second_c, allow_transformer=allow_transformer)

        if result["similarity_score"] >= 0.50:
            if existing:
                existing.similarity_score = result["similarity_score"]
                existing.semantic_score = result["semantic_score"]
                existing.keyword_score = result["keyword_score"]
                existing.category_score = result["category_score"]
                existing.context_score = result["context_score"]
                existing.relationship_type = result["relationship_type"]
                existing.matching_evidence = result["matching_evidence"]
                existing.conflicting_evidence = result["conflicting_evidence"]
                existing.algorithm_version = result["algorithm_version"]
                detected_relationships.append(existing)
            else:
                rel = OverlapRelationship(
                    first_complaint_id=first_c.id,
                    second_complaint_id=second_c.id,
                    similarity_score=result["similarity_score"],
                    semantic_score=result["semantic_score"],
                    keyword_score=result["keyword_score"],
                    category_score=result["category_score"],
                    context_score=result["context_score"],
                    relationship_type=result["relationship_type"],
                    review_status="Pending Review",
                    matching_evidence=result["matching_evidence"],
                    conflicting_evidence=result["conflicting_evidence"],
                    algorithm_version=result["algorithm_version"],
                    created_at=datetime.utcnow(),
                )
                session.add(rel)
                session.flush()
                detected_relationships.append(rel)
        else:
            if existing and existing.review_status == "Pending Review":
                session.delete(existing)

    if auto_save:
        try:
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save overlap relationships: {e}")

    return detected_relationships
