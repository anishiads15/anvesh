import re
import logging
from typing import Dict, List, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# Predefined domain taxonomies with target subcategories and characteristic keywords
CATEGORY_TAXONOMY = {
    "Ragging and Student Harassment": {
        "subcategories": [
            "Senior student harassment",
            "Hostel ragging incidents",
            "Verbal and psychological intimidation",
            "Anti-ragging cell inaction",
        ],
        "keywords": [
            "ragging", "harassment", "harassed", "bully", "bullying", "senior",
            "intimidation", "abuse", "mental torture", "threatened", "hostel ragging",
            "anti ragging", "squad", "victim", "freshers",
        ],
        "prototypes": [
            "Incidents of student ragging, verbal harassment, physical bullying, and intimidation by seniors.",
            "Hostel ragging, psychological distress inflicted on junior students, and failure of anti-ragging squad.",
        ],
    },
    "Financial Issues and Fee Irregularities": {
        "subcategories": [
            "Capitation fee & overcharging",
            "Refusal of tuition refund",
            "Document withholding for fees",
            "Unauthorized fine collection",
        ],
        "keywords": [
            "fee", "tuition", "overcharging", "refund", "deposit", "caution money",
            "withholding documents", "original certificates", "receipt", "bribery",
            "capitation", "fine", "extortion", "hidden charges",
        ],
        "prototypes": [
            "Institute overcharging tuition fees, refusing mandatory admission fee refunds, or withholding original documents.",
            "Arbitrary monetary fines and unapproved development fees collected without official AICTE sanction.",
        ],
    },
    "Scholarship Delays": {
        "subcategories": [
            "AICTE Pragati / Saksham delay",
            "State welfare stipend pending",
            "Institute verification backlog",
            "DBT account transfer failure",
        ],
        "keywords": [
            "scholarship", "stipend", "pragati", "saksham", "fellowship", "disbursal",
            "dbt", "portal verification", "financial aid", "grant", "pending scholarship",
        ],
        "prototypes": [
            "Severe delays in scholarship disbursal, pending institutional biometric verification, and unpaid student stipends.",
            "AICTE and government scholarship funds not credited to student accounts due to administrative negligence.",
        ],
    },
    "Laboratory Equipment and Infrastructure": {
        "subcategories": [
            "Non-functional apparatus",
            "Missing instruments",
            "Outdated computing hardware",
            "Safety gear absence in labs",
        ],
        "keywords": [
            "laboratory", "lab", "equipment", "apparatus", "machine", "machinery",
            "experiment", "practical", "instrument", "oscilloscope", "lathe", "specimen",
            "chemicals", "multimeter", "microscope", "testing machine", "trainer kit",
            "computers", "hardware failure", "calibration", "tensile", "workshop",
        ],
        "prototypes": [
            "Laboratory instruments and experimental equipment are broken, non-functional, or unavailable for practical classes.",
            "Testing machinery, workshop apparatus, and specialized engineering lab tools are out of order.",
        ],
    },
    "Hostel and Accommodation": {
        "subcategories": [
            "Hostel living conditions",
            "Geyser and hot water failure",
            "Mess & canteen food hygiene",
            "Room maintenance & overcrowding",
        ],
        "keywords": [
            "hostel", "accommodation", "dormitory", "geyser", "hot water", "mess",
            "canteen", "food quality", "food poisoning", "insects", "meal", "warden",
            "room allocation", "bed", "living condition",
        ],
        "prototypes": [
            "Hostel accommodation issues, lack of hot water geysers, substandard living conditions, and unhygienic mess meals.",
            "Residential student grievances regarding unlivable dormitories, pest infestation, and canteen food hygiene.",
        ],
    },
    "Faculty Misconduct": {
        "subcategories": [
            "Faculty shortage & absenteeism",
            "Unprofessional conduct & harassment",
            "Unqualified instructors",
            "Biased internal evaluation",
        ],
        "keywords": [
            "faculty", "teacher", "professor", "lecturer", "instructor", "shortage",
            "attendance", "absent", "syllabus", "unqualified", "staff", "misconduct",
            "unprofessional", "hod", "proxy teacher", "teaching quality",
        ],
        "prototypes": [
            "Shortage of teaching faculty, absent professors, unqualified lecturers, and faculty misconduct.",
            "Instructors failing to conduct classes, abusive behavior by department staff, and dereliction of academic duties.",
        ],
    },
    "Academic and Examination Issues": {
        "subcategories": [
            "Curriculum delays",
            "Examination schedule disruption",
            "Evaluation irregularities",
            "Practical assessment dispute",
        ],
        "keywords": [
            "curriculum", "syllabus", "exam", "examination", "marks", "internal marks",
            "evaluation", "grading", "assessment", "attendance criteria", "academic calendar",
            "paper leak", "admit card", "hall ticket",
        ],
        "prototypes": [
            "Academic delays, non-conduction of classes according to syllabus, exam evaluation discrepancies, and grading errors.",
            "Unfair exam scheduling, sudden cancellation of semesters, and withheld exam hall tickets.",
        ],
    },
    "Discrimination and Student Welfare": {
        "subcategories": [
            "Caste or community bias",
            "Gender discrimination",
            "Differently-abled student neglect",
            "Welfare committee inactivity",
        ],
        "keywords": [
            "discrimination", "bias", "caste", "gender", "disability", "wheelchair",
            "ramp", "welfare", "sc", "st", "obc", "minority", "prejudice",
            "equal opportunity", "mental health", "counselor",
        ],
        "prototypes": [
            "Unfair discrimination based on caste, gender, region, or disability status in campus activities or academic scoring.",
            "Neglect of student welfare, lack of accessibility ramps, and non-compliance with equal opportunity provisions.",
        ],
    },
    "Safety and Security": {
        "subcategories": [
            "Campus security & vigilance",
            "Boundary wall and trespassers",
            "Fire safety non-compliance",
            "CCTV & night lighting",
        ],
        "keywords": [
            "security", "guard", "cctv", "boundary wall", "lighting", "night safety",
            "fire safety", "fire extinguisher", "fire alarm", "emergency exit",
            "trespasser", "theft", "gate pass", "patrol",
        ],
        "prototypes": [
            "Inadequate security vigilance, broken boundary walls, unauthorized intruders, and non-functional CCTV surveillance.",
            "Expired fire extinguishers, locked fire exits, and severe physical security threats on institution premises.",
        ],
    },
    "Sanitation and Drinking Water": {
        "subcategories": [
            "Water purifier breakdown",
            "Restroom & washroom cleanliness",
            "Drainage and sewage overflow",
            "Water shortage",
        ],
        "keywords": [
            "drinking water", "purifier", "water", "washroom", "toilet", "sanitation",
            "drainage", "sewage", "cleanliness", "hygiene", "leaking pipe", "overkill",
            "restroom", "plumbing", "water contamination",
        ],
        "prototypes": [
            "Campus drinking water purifiers broken or leaking contaminated water, and unhygienic washroom facilities.",
            "Restroom sanitation failures, choked drainage lines, sewage overflow, and lack of running tap water.",
        ],
    },
    "Library and Learning Resources": {
        "subcategories": [
            "Deficit of textbooks & references",
            "Digital journal access unavailable",
            "Library operating hours restriction",
            "E-learning portal outage",
        ],
        "keywords": [
            "library", "books", "textbook", "reference book", "journals", "subscription",
            "digital library", "ieee", "springer", "reading room", "e-books", "librarian",
        ],
        "prototypes": [
            "Deficit of prescribed syllabus textbooks, outdated editions, and non-renewal of digital journal subscriptions.",
            "Campus library closed during exams, damaged reading room facilities, and unavailable research resources.",
        ],
    },
    "Other": {
        "subcategories": [
            "General administrative grievance",
            "Campus amenities & transportation",
            "Environmental & waste disposal",
        ],
        "keywords": [
            "bus", "transportation", "canteen", "wifi", "internet", "parking", "sports",
            "gym", "miscellaneous", "general",
        ],
        "prototypes": [
            "General administrative matters, campus bus transportation issues, and miscellaneous institutional grievances.",
        ],
    },
    "Fee Overcharging / Capitation": {
        "subcategories": [
            "Capitation fee demands",
            "Excess tuition fee collection",
            "Non-refundable deposits",
            "Development fee extortion",
        ],
        "keywords": [
            "capitation", "fee overcharging", "tuition hike", "extortion", "hidden fees",
            "receipt refused", "excess fee", "cash demand", "quota fees", "caution deposit",
        ],
        "prototypes": [
            "Demanding excessive capitation fees or charging tuition in excess of state regulatory fee committee limits.",
            "Coercive fee extortion and refusing official payment receipts under threat of debarment.",
        ],
    },
    "Infrastructure & Laboratory Deficit": {
        "subcategories": [
            "Deficient lab apparatus",
            "Missing safety gear",
            "Uncalibrated test rigs",
            "Counterfeit lab compliance reports",
        ],
        "keywords": [
            "laboratory deficit", "equipment non-functional", "broken machines", "workshop deficiency",
            "empty lab spaces", "uncalibrated apparatus", "safety gear deficit", "workshop closed",
        ],
        "prototypes": [
            "Non-existent specialized laboratories, non-functional tensile machines, and counterfeit compliance reports.",
            "Severe laboratory deficit preventing engineering students from conducting mandatory practical syllabus.",
        ],
    },
    "Withholding Original Certificates": {
        "subcategories": [
            "Withholding marksheets",
            "Transfer certificate withheld",
            "Degree certificate retention",
            "Coercive retention for dues",
        ],
        "keywords": [
            "withholding", "original certificates", "marksheet withheld", "transfer certificate",
            "migration certificate", "retention of documents", "hostage documents", "degree certificate",
        ],
        "prototypes": [
            "Institution illegally withholding original secondary/diploma marksheets and transfer certificates to force fees.",
            "Refusal to return original degree certificates upon course completion in violation of AICTE norms.",
        ],
    },
    "Admissions & Affiliation Irregularities": {
        "subcategories": [
            "Unapproved intake",
            "Affiliation deficit",
            "Management quota irregularities",
            "False accreditation claims",
        ],
        "keywords": [
            "admissions irregularity", "affiliation", "unapproved intake", "management quota",
            "backdoor admission", "university affiliation", "nba accreditation fraud", "aph violation",
        ],
        "prototypes": [
            "Admitting students beyond sanctioned AICTE intake and operating unapproved course shifts without university affiliation.",
            "Irregular admission counseling procedures and fraudulent claims of NBA/NAAC accreditation.",
        ],
    },
    "Governance Malpractice & Retaliation": {
        "subcategories": [
            "Student victimisation",
            "Whistleblower retaliation",
            "Debarment without inquiry",
            "Governing council malpractice",
        ],
        "keywords": [
            "retaliation", "governance malpractice", "victimisation", "student council debarment",
            "police notice threat", "arbitrary suspension", "illegal fine", "whistleblower", "suppression",
        ],
        "prototypes": [
            "Illegal suspension, police threats, and retaliatory disciplinary notices against student representatives for reporting deficits.",
            "Severe administrative malpractice, absence of statutory redressal committee, and victimization of complainants.",
        ],
    },
    "Misappropriation of Grant Funds": {
        "subcategories": [
            "PMKVY stipend embezzlement",
            "MODROBS grant diversion",
            "Research fund siphoning",
            "Fabricated beneficiary lists",
        ],
        "keywords": [
            "misappropriation", "grant funds", "pmkvy", "modrobs", "embezzlement",
            "fabricated aadhaar", "stipend diverted", "research grant fraud", "procurement fraud",
        ],
        "prototypes": [
            "Embezzlement of AICTE/government research grants, fabricated student beneficiary records under PMKVY, and diverted funding.",
            "Misappropriation of modernization and removal of obsolescence (MODROBS) equipment grants.",
        ],
    },
    "Faculty Non-Payment & Understaffing": {
        "subcategories": [
            "Salary arrears & non-payment",
            "Ghost faculty on rolls",
            "Unqualified teaching staff",
            "Cadre ratio violation",
        ],
        "keywords": [
            "salary non-payment", "salary arrears", "faculty understaffing", "ghost faculty",
            "unpaid teachers", "cadre ratio", "7th pay commission", "unqualified faculty", "salary cut",
        ],
        "prototypes": [
            "Professors and lecturers unpaid for several months, persistent salary arrears, and cadre ratio violations.",
            "Use of ghost faculty registrations during inspection while actual academic departments are severely understaffed.",
        ],
    },
    "Unapproved Courses & Excess Intake": {
        "subcategories": [
            "Unapproved branch/course",
            "Over-intake beyond approval",
            "Fake dual degree programs",
            "Unsanctioned off-campus center",
        ],
        "keywords": [
            "unapproved courses", "excess intake", "unapproved branch", "counterfeit degrees",
            "unsanctioned campus", "intake violation", "approval process handbook", "fake specialization",
        ],
        "prototypes": [
            "Institution conducting unapproved technical programs and admitting batches without valid AICTE extension of approval.",
            "Excess student intake exceeding sanctioned council intake limits causing degree invalidation risk.",
        ],
    },
}

# Backward compatibility alias map
LEGACY_CATEGORY_MAP = {
    "Infrastructure": "Laboratory Equipment and Infrastructure",
    "Laboratory and equipment": "Laboratory Equipment and Infrastructure",
    "Faculty and staffing": "Faculty Misconduct",
    "Academic quality": "Academic and Examination Issues",
    "Student facilities": "Hostel and Accommodation",
    "Safety and accessibility": "Safety and Security",
    "Administrative compliance": "Other",
    "Capitation Fee Demand": "Fee Overcharging / Capitation",
    "Harassment / Ragging": "Ragging and Student Harassment",
    "Ragging & Student Harassment": "Ragging and Student Harassment",
    "Fee Overcharging": "Fee Overcharging / Capitation",
    "Capitation": "Fee Overcharging / Capitation",
}

def normalize_category_name(cat_name: str) -> str:
    """Normalizes any legacy or variant category name into canonical 20 standardized categories."""
    if not cat_name:
        return "Other"
    clean = cat_name.strip()
    if clean in CATEGORY_TAXONOMY:
        return clean
    return LEGACY_CATEGORY_MAP.get(clean, clean)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "in", "on", "at",
    "to", "for", "with", "by", "from", "of", "about", "as", "it", "this", "that",
    "these", "those", "we", "our", "my", "i", "they", "their", "student", "students",
    "college", "institute", "institution", "department", "complaint", "issue", "problem",
    "has", "have", "had", "been", "due", "cannot", "because", "two", "weeks", "days",
    "out", "order", "down", "not", "some", "all", "remained", "can", "will", "would",
    "there", "here", "also", "very", "much", "more", "such",
}

# Domain lemmatization / canonical forms
TOKEN_NORMALIZATIONS = {
    "laboratory": "lab",
    "laboratories": "lab",
    "labs": "lab",
    "machinery": "machine",
    "machines": "machine",
    "experiments": "experiment",
    "experimental": "experiment",
    "apparatuses": "apparatus",
    "professors": "professor",
    "teachers": "teacher",
    "lecturers": "lecturer",
    "classrooms": "classroom",
    "purifiers": "purifier",
    "facilities": "facility",
    "equipments": "equipment",
    "shortages": "shortage",
    "deficits": "deficit",
}

# Lazy loading cache for transformer model
_TRANSFORMER_MODEL = None
_TRANSFORMER_LOAD_ATTEMPTED = False


def _get_transformer_model():
    """Lazily load sentence-transformers model if available and configured."""
    global _TRANSFORMER_MODEL, _TRANSFORMER_LOAD_ATTEMPTED
    if _TRANSFORMER_LOAD_ATTEMPTED:
        return _TRANSFORMER_MODEL

    _TRANSFORMER_LOAD_ATTEMPTED = True
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading sentence-transformers model 'all-MiniLM-L6-v2'...")
        _TRANSFORMER_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("SentenceTransformer successfully loaded!")
    except Exception as e:
        logger.warning(f"SentenceTransformer not loaded ({e}). Operating in TF-IDF fallback mode.")
        _TRANSFORMER_MODEL = None

    return _TRANSFORMER_MODEL


def normalize_token(word: str) -> str:
    """Normalizes word variants and common educational pluralizations."""
    w = word.lower().strip()
    return TOKEN_NORMALIZATIONS.get(w, w)


def extract_keywords(text: str, top_k: int = 8) -> List[str]:
    """Extract salient domain keywords from complaint title and description."""
    raw_words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    filtered = [normalize_token(w) for w in raw_words if w not in STOPWORDS and normalize_token(w) not in STOPWORDS]
    if not filtered:
        return []

    # Frequency counting
    counts: Dict[str, int] = {}
    for word in filtered:
        counts[word] = counts.get(word, 0) + 1

    # Give bonus to category-specific keywords
    all_cat_keywords = set()
    for cat_data in CATEGORY_TAXONOMY.values():
        for kw in cat_data["keywords"]:
            all_cat_keywords.update([normalize_token(w) for w in kw.split()])

    scored = []
    for word, count in counts.items():
        weight = count * (2.5 if word in all_cat_keywords else 1.0)
        scored.append((weight, word))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [word for _, word in scored[:top_k]]


def categorize_complaint(
    title: str,
    description: str,
    allow_semantic: bool = True
) -> Dict:
    """Classifies a complaint into AICTE category, predicts subcategory, extracts keywords,
    and returns transparent confidence and evidence.
    """
    combined_text = f"{title}. {description}".strip()
    keywords = extract_keywords(combined_text)

    # 1. Keyword-based matching score for each category
    lower_text = combined_text.lower()
    keyword_scores = {}
    matched_terms = {}

    for cat, data in CATEGORY_TAXONOMY.items():
        hits = 0
        hits_terms = []
        for kw in data["keywords"]:
            if " " in kw:
                if kw in lower_text:
                    hits += 3.0
                    hits_terms.append(kw)
            else:
                pattern = r"\b" + re.escape(kw) + r"\b"
                matches = len(re.findall(pattern, lower_text))
                if matches > 0:
                    hits += matches * 1.8
                    hits_terms.append(kw)
        keyword_scores[cat] = hits
        matched_terms[cat] = hits_terms

    # Normalize keyword scores
    max_kw = max(keyword_scores.values()) if keyword_scores else 0
    normalized_kw_scores = {
        cat: (score / max_kw) if max_kw > 0 else 0.0
        for cat, score in keyword_scores.items()
    }

    # 2. Semantic matching if available
    semantic_scores = {}
    model = _get_transformer_model() if allow_semantic else None
    used_semantic = False

    if model is not None:
        try:
            doc_embedding = model.encode([combined_text])
            for cat, data in CATEGORY_TAXONOMY.items():
                proto_embeddings = model.encode(data["prototypes"])
                sims = cosine_similarity(doc_embedding, proto_embeddings)[0]
                semantic_scores[cat] = float(max(sims))
            used_semantic = True
        except Exception as e:
            logger.warning(f"Error during semantic encoding: {e}. Falling back to TF-IDF.")
            used_semantic = False

    # 3. TF-IDF Fallback if semantic model was not used
    if not used_semantic:
        try:
            proto_docs = []
            cat_list = list(CATEGORY_TAXONOMY.keys())
            for cat in cat_list:
                data = CATEGORY_TAXONOMY[cat]
                proto_docs.append(" ".join(data["prototypes"]) + " " + " ".join(data["keywords"]))

            all_docs = [combined_text] + proto_docs
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
            tfidf_matrix = vectorizer.fit_transform(all_docs)
            tfidf_sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])[0]

            for idx, cat in enumerate(cat_list):
                semantic_scores[cat] = float(tfidf_sims[idx])
        except Exception as e:
            logger.error(f"Error during TF-IDF calculation: {e}")
            for cat in CATEGORY_TAXONOMY.keys():
                semantic_scores[cat] = 0.0

    # 4. Hybrid combination
    final_scores = {}
    for cat in CATEGORY_TAXONOMY.keys():
        kw_s = normalized_kw_scores.get(cat, 0.0)
        sem_s = semantic_scores.get(cat, 0.0)
        if used_semantic:
            score = (sem_s * 0.60) + (kw_s * 0.40)
        else:
            score = (sem_s * 0.50) + (kw_s * 0.50)
        final_scores[cat] = round(score, 4)

    sorted_cats = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    best_cat, best_score = sorted_cats[0]

    CONFIDENCE_THRESHOLD = 0.18
    if best_score < CONFIDENCE_THRESHOLD:
        best_cat = "Other"
        predicted_subcategory = "Unclassified / Low Confidence"
        confidence_level = "Low"
        explanation = (
            f"The complaint text did not exhibit sufficient match with standard categories "
            f"(maximum match score: {best_score:.2f} < {CONFIDENCE_THRESHOLD}). Manual review recommended."
        )
    else:
        subcats = CATEGORY_TAXONOMY[best_cat]["subcategories"]
        subcat_hits = []
        for sub in subcats:
            sub_words = [normalize_token(w) for w in re.findall(r"[a-zA-Z]{3,}", sub) if w.lower() not in STOPWORDS]
            overlap = sum(1 for w in sub_words if w in lower_text or w in [normalize_token(x) for x in re.findall(r"[a-zA-Z]{3,}", lower_text)])
            subcat_hits.append((overlap, sub))
        subcat_hits.sort(key=lambda x: x[0], reverse=True)
        predicted_subcategory = subcat_hits[0][1]

        confidence_level = "High" if best_score >= 0.50 else "Moderate"
        matching_kws = matched_terms.get(best_cat, [])[:4]
        kw_phrase = f"matching terms [{', '.join(matching_kws)}]" if matching_kws else "contextual similarity"
        explanation = (
            f"Classified as '{best_cat}' ({confidence_level} confidence: {best_score:.2f}) based on {kw_phrase} "
            f"and compatibility with {predicted_subcategory}."
        )

    source_label = (
        "AI - Semantic Model (MiniLM + Hybrid Keyword)"
        if used_semantic
        else "AI - TF-IDF Fallback Engine"
    )

    return {
        "category": best_cat,
        "subcategory": predicted_subcategory,
        "confidence_score": float(best_score),
        "confidence_level": confidence_level,
        "source": source_label,
        "keywords": keywords,
        "explanation": explanation,
        "all_scores": final_scores,
    }
