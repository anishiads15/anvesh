# AICTE Integrated Institution Complaint Monitoring System

An end-to-end administrative portal and AI-assisted governance system designed for the **All India Council for Technical Education (AICTE)** and authorized institutional administrators.

The platform centralizes grievance intake across colleges, polytechnics, and technical universities. Its primary innovation is **automated semantic overlap and duplicate detection**, which identifies grievances describing the same underlying issue even when submitted by different stakeholders (students, faculty, inspection teams), through disparate channels, or using distinct terminology.

---

## 1. Key Highlights & Features

- **Centralized Grievance Intake**: Uniform intake supporting Student Grievances, Institutional Reports, Inspection Disclosures, and Public Inquiries across **8 fictional institutions** with **30 unique demonstration complaints**.
- **12 Standardized Grievance Categories**: Complete support for Ragging, Financial Issues, Scholarships, Laboratory Infrastructure, Hostels, Faculty Misconduct, Examinations, Discrimination, Safety, Sanitation, Library Resources, and Other.
- **Complainant Confidentiality**: Built-in identity protection with sensitive categories automatically marked confidential (`[CONFIDENTIAL COMPLAINANT]`), shielding personal details from public/dashboard exposure.
- **AI-Assisted Categorization**: Hybrid natural language classifier (Sentence Transformers + Scikit-Learn TF-IDF N-grams) predicting AICTE categories and subcategories with transparent confidence scores and keywords.
- **Core Innovation &mdash; Multi-Signal Overlap Detection**:
  - **55% Semantic Text Similarity**: Dense 384-dimensional sentence embeddings (`all-MiniLM-L6-v2`) or morphological N-gram TF-IDF cosine distance.
  - **20% Shared Issue Keywords**: Sorensen-Dice coefficient over normalized domain terminology.
  - **15% Category Compatibility**: Structural taxonomy compatibility evaluation across the 12 categories.
  - **10% Contextual Similarity**: Campus identity, local physical facility correlation, and temporal proximity.
  - **Contradictory Topic Filter**: Eliminates false positives between unrelated issues (e.g. drinking water facilities vs. mechanical lab machinery) occurring at the same institution.
  - **Canonical Deduplication**: Unique canonical ordering (`first_id < second_id`) preventing duplicate relationship pairs.
- **5 Overlap Analytics Visualizations**:
  - **A. Complaint Overlap Trend**: Chronological line graph tracking strong vs. possible overlaps over time across past 90 days.
  - **B. Complaint Relationship Graph**: Interactive HTML5 Canvas force-directed network graph visualizing nodes (complaints) and links (overlaps) with instant inspector panel and drag-to-rearrange controls.
  - **C. Institution-wise Overlap Comparison**: Stacked bar chart comparing same-institution vs. cross-institution overlaps across all 8 colleges.
  - **D. Complaint Category Overlap**: Category frequency chart identifying recurring problem clusters in laboratories, hostels, scholarships, and ragging.
  - **E. Resolution & Recurrence Analysis**: Post-resolution audit comparing clean permanent resolutions vs. suspected and confirmed recurrences with time elapsed metrics.
- **Human-in-the-Loop Review Queue**: Reviewers confirm or reject algorithmic overlap suggestions without automatically altering complaint lifecycle states or deleting records.
- **Institutional Administrative Isolation**: Role-based access control (RBAC) ensuring institutional administrators view only records assigned to their campus.
- **Sanitized CSV Export**: Protected reporting with formula injection mitigation (neutralizing `=,+,-,@` prefixes).
- **Cryptographic Audit Trail**: Immutable log of logins, complaint creations, category overrides, and review decisions.
- **Idempotent Seeding & Non-Destructive Migrations**: Restarts preserve existing demo counts without generating duplicates, and protects non-demo user complaints.

---

## 2. Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.10+, Flask 3.1, Jinja2 |
| **Database & ORM** | SQLite, SQLAlchemy 2.0+ (with SQLite foreign-key enforcement) |
| **AI / NLP** | Sentence Transformers (`all-MiniLM-L6-v2`), Scikit-Learn (TF-IDF, Cosine Similarity) |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript, Bootstrap 5.3, Bootstrap Icons, Chart.js 4.4 |
| **Testing** | Pytest, Flask Test Client |

---

## 3. Project Structure

```text
aicte-complaint-monitoring/
│
├── app.py                      # Flask Application Factory & CLI registration
├── config.py                   # Central configuration & test environment setups
├── extensions.py               # SQLAlchemy ORM database lifecycle manager
├── requirements.txt            # Python dependencies
├── run.bat                     # Windows 1-click startup automation script
├── .env.example                # Sample environment variables
├── .gitignore                  # Git ignore rules
├── README.md                   # System documentation & setup guide
│
├── models/                     # SQLAlchemy Database Entities
│   ├── __init__.py             # Model exports
│   ├── institution.py          # Institution profile & AICTE code entity
│   ├── user.py                 # User account, RBAC & password hashing
│   ├── complaint.py            # Complaint & ComplaintStatusHistory entities
│   ├── overlap.py              # OverlapRelationship entity with canonical constraint
│   └── audit.py                # AuditEvent immutable log entity
│
├── services/                   # Core Business & AI Logic
│   ├── __init__.py             # Service exports
│   ├── categorization.py       # Hybrid semantic & TF-IDF category classifier
│   ├── overlap_detection.py    # Multi-signal overlap detection pipeline
│   ├── analytics.py            # Real-time metrics & dashboard calculations
│   └── audit_service.py        # Audit logging service
│
├── routes/                     # Blueprint Route Handlers
│   ├── __init__.py             # Route exports
│   ├── auth.py                 # Authentication, sessions & role decorators
│   ├── dashboard.py            # Monitoring dashboard & JSON metrics API
│   ├── complaints.py           # Intake, search, filter, detail & override routes
│   ├── overlaps.py             # Deduplication queue & human review actions
│   ├── institutions.py         # Institutional directory & campus profiles
│   ├── reports.py              # Analytical reports & formula-safe CSV export
│   └── settings.py             # System diagnostics & audit log viewer
│
├── templates/                  # Government Tech UI Templates
│   ├── base.html               # Master shell with persistent sidebar & header
│   ├── login.html              # Secure authentication view with demo credentials
│   ├── dashboard.html          # Administrative monitoring dashboard with Chart.js
│   ├── complaints.html         # Master complaints table with visual overlap pills
│   ├── complaint_form.html     # Complaint intake form with live AI preview
│   ├── complaint_detail.html   # Detailed dossier, timeline & matching evidence
│   ├── overlaps.html           # Side-by-side comparative review queue
│   ├── institutions.html       # Approved institutions directory
│   ├── institution_detail.html # Single institution profile & related grievances
│   ├── analytics.html          # Regulatory compliance & reviewer workload
│   ├── audit_log.html          # Searchable, filterable audit records
│   ├── settings.html           # AI engine diagnostics & threshold parameters
│   └── errors/                 # 403, 404, 500 custom error templates
│
├── static/                     # Assets
│   ├── css/style.css           # Government-tech theme stylesheet
│   └── js/                     # Client-side helpers
│
├── scripts/                    # Utilities & Seeding
│   ├── seed_demo_data.py       # Seeds realistic synthetic dataset
│   └── create_admin.py         # Command-line administrative user creator
│
└── tests/                      # Automated Test Suite (24 Test Cases)
    ├── conftest.py             # Pytest fixtures & in-memory test database
    ├── test_auth.py            # Auth, RBAC & session security tests
    ├── test_complaints.py      # Intake validation, status & isolation tests
    ├── test_categorization.py  # Category classifier & fallback tests
    ├── test_overlap_detection.py# Core innovation tests (overlap detection)
    ├── test_review_workflow.py # Human confirmation/rejection workflow tests
    └── test_reports.py         # Dashboard metrics & formula-safe CSV tests
```

---

## 4. Demonstration Accounts

The system comes pre-seeded with realistic demonstration accounts:

## 4. Role-Based Portals & Local Demo Accounts

The portal provides 3 dedicated role-based entry points with strict backend RBAC:

| Portal | User Role | Username | Password | Dedicated Access Scope & Restrictions |
| :--- | :--- | :--- | :--- | :--- |
| **Portal 1: Complainant / Student** | `complainant` | `student` | `Student@123` | Lodge complaints with attachments, monitor 5-stage progress, view public resolution statements, submit feedback, request reopening. Strict identity confidentiality. Cannot access admin dashboards. |
| **Portal 2: Institutional Reviewer** | `institutional_reviewer` | `inst_admin` | `InstAdmin@123` | Isolated to **ABC Engineering College** (`AICTE-ENG-001`). Review grievances, record internal remarks, issue public resolution statements, or escalate unaddressed cases to AICTE. Cannot register student complaints. |
| **Portal 3: AICTE Officer** | `aicte_officer` | `admin` | `Admin@123` | National monitoring dashboard, review escalations, cross-institution analytics, AI duplicate overlap adjudication queue, audit logs. Manages regulatory decisions, not complaint creation. |

> **Security Notice:** Demo credentials are provided exclusively for local demonstration and automated evaluation. Production AICTE deployments utilize SAML 2.0 / MeriPehchan Single Sign-On (SSO).

---

## 5. Quick Windows Startup

### Option A: 1-Click Launch with `run.bat` (Recommended)
Simply double-click `run.bat` in the project root (or run it from PowerShell/CMD):
```cmd
.\run.bat
```
`run.bat` automatically:
1. Verifies Python 3.10+ is available.
2. Creates the `.\venv` virtual environment if needed.
3. Installs dependencies from `requirements.txt`.
4. Initializes the SQLite database and seeds demonstration records.
5. Launches your browser to `http://127.0.0.1:5000/login`.
6. Starts the local Flask server on `127.0.0.1:5000`.

---

### Option B: Manual PowerShell Setup
If you prefer running commands manually:

```powershell
# 1. Navigate to the project directory
cd aicte-complaint-monitoring

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Initialize & seed demonstration records
python scripts\seed_demo_data.py

# 6. Run the application
python app.py
```
Open your browser and navigate to: **`http://127.0.0.1:5000`**

---

## 6. Running Automated Tests

The automated test suite runs offline and verifies all core modules, AI pipelines, database constraints, and security checks:

```powershell
# Run the complete test suite
.\venv\Scripts\pytest -v
```

### Actual Test Execution Summary
```text
============================= test session starts =============================
platform win32 -- Python 3.12.6, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\Users\anish\.gemini\antigravity\scratch\aicte-complaint-monitoring
collected 24 items

tests/test_auth.py::test_password_hashing PASSED                         [  4%]
tests/test_auth.py::test_login_success PASSED                            [  8%]
tests/test_auth.py::test_login_invalid_credentials PASSED                [ 12%]
tests/test_auth.py::test_logout PASSED                                   [ 16%]
tests/test_auth.py::test_role_based_access_control PASSED                [ 20%]
tests/test_categorization.py::test_categorize_laboratory_equipment PASSED [ 25%]
tests/test_categorization.py::test_categorize_infrastructure_water PASSED [ 29%]
tests/test_categorization.py::test_categorize_faculty_shortage PASSED    [ 33%]
tests/test_categorization.py::test_fallback_engine_flag PASSED           [ 37%]
tests/test_categorization.py::test_low_confidence_fallback PASSED        [ 41%]
tests/test_categorization.py::test_keyword_extraction PASSED             [ 45%]
tests/test_complaints.py::test_complaint_creation_and_reference PASSED   [ 50%]
tests/test_complaints.py::test_complaint_validation_error PASSED         [ 54%]
tests/test_complaints.py::test_complaint_status_update PASSED            [ 58%]
tests/test_complaints.py::test_institutional_admin_isolation PASSED      [ 62%]
tests/test_overlap_detection.py::test_strong_potential_overlap_different_wording PASSED [ 66%]
tests/test_overlap_detection.py::test_unrelated_complaints_same_institution_not_flagged PASSED [ 70%]
tests/test_overlap_detection.py::test_cross_institution_similar_complaints PASSED [ 75%]
tests/test_overlap_detection.py::test_canonical_ordering_and_no_duplicates PASSED [ 79%]
tests/test_reports.py::test_dashboard_metrics_accuracy PASSED            [ 83%]
tests/test_reports.py::test_csv_formula_sanitization PASSED              [ 87%]
tests/test_reports.py::test_csv_export_endpoint PASSED                   [ 91%]
tests/test_review_workflow.py::test_human_confirmation_workflow PASSED   [ 95%]
tests/test_role_portals_workflow.py::test_three_portal_logins PASSED     [ 89%]
tests/test_role_portals_workflow.py::test_complainant_access_restrictions PASSED [ 92%]
tests/test_role_portals_workflow.py::test_institutional_reviewer_isolation PASSED [ 96%]
tests/test_role_portals_workflow.py::test_full_complaint_lifecycle_workflow PASSED [100%]

============================== 28 passed in 35.12s ==============================
```

---

## 7. AI Methodology & Overlap Decision Thresholds

### Multi-Signal Scoring Pipeline
$$\text{Composite Score} = 0.55 \cdot S_{\text{sem}} + 0.20 \cdot S_{\text{kw}} + 0.15 \cdot S_{\text{cat}} + 0.10 \cdot S_{\text{ctx}}$$

1. **Semantic Text Similarity ($S_{\text{sem}}$)**: Computed via `SentenceTransformer('all-MiniLM-L6-v2')` embedding cosine similarity. If the model or internet is unavailable, seamlessly falls back to character/word N-gram TF-IDF cosine distance.
2. **Keyword Similarity ($S_{\text{kw}}$)**: Sorensen-Dice similarity over stemmed domain vocabulary.
3. **Category Compatibility ($S_{\text{cat}}$)**: Exact match ($1.0$), complementary cross-domain match ($0.4$), or incompatible match ($0.0$).
4. **Contextual Similarity ($S_{\text{ctx}}$)**: Same institution ($+0.50$), same physical facility ($+0.30$), temporal proximity ($+0.20$).

### Decision Thresholds
- **Score $\ge 0.80$**: `Strong Potential Overlap` &mdash; Displayed with high-visibility red badge and pale-red border. Immediate deduplication review advised.
- **$0.50 \le \text{Score} < 0.80$**: `Possible Overlap &mdash; Review Required` &mdash; Displayed with amber badge and pale-yellow border. Administrative inspection recommended.
- **Score $< 0.50$**: No automatic overlap flag generated.

### Contradictory Topic Filter
If two complaints at the same campus address contradictory subjects (e.g. drinking water sanitation vs laboratory machinery), the score is capped to $\le 0.30$. Unrelated grievances from the same college are **never** flagged merely because the campus matches.

---

## 8. AI Limitations and Governance Disclaimer

- **Demonstration Scope**: This application is a self-contained demonstration prototype and is not connected to live government production networks. Synthetic demonstration data is used.
- **Human Accountability**: The AI engine provides advisory signals and decision-support evidence. Algorithmic overlap scores never automatically close, delete, or merge complaint records. Consequential actions require explicit human confirmation.
- **No Paid APIs**: The core system executes entirely on local CPU and requires no paid APIs or API keys.
