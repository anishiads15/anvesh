import pytest
from services.categorization import categorize_complaint, extract_keywords


def test_categorize_laboratory_equipment():
    """Test AI categorization for laboratory equipment breakdown."""
    title = "Mechanical engineering testing machines non-functional"
    desc = "All laboratory apparatus and lathe machine equipment have broken down preventing practical classes."
    result = categorize_complaint(title, desc, allow_semantic=False)

    assert result["category"] in ["Laboratory Equipment and Infrastructure", "Laboratory and equipment"]
    assert result["confidence_score"] > 0.40
    assert "keywords" in result
    assert any("machine" in kw or "equipment" in kw or "apparatus" in kw or "laboratory" in kw for kw in result["keywords"])


def test_categorize_infrastructure_water():
    """Test AI categorization for drinking water facility grievance."""
    title = "Drinking water purifier damaged"
    desc = "Campus water purifier and washroom sanitation facilities are completely broken and leaking water."
    result = categorize_complaint(title, desc, allow_semantic=False)

    assert result["category"] in ["Sanitation and Drinking Water", "Infrastructure"]
    assert result["confidence_score"] > 0.40


def test_categorize_faculty_shortage():
    """Test AI categorization for teaching faculty shortage."""
    title = "Severe shortage of teaching faculty"
    desc = "Computer science department has absent professors and vacant teacher posts for three weeks."
    result = categorize_complaint(title, desc, allow_semantic=False)

    assert result["category"] in ["Faculty Misconduct", "Faculty and staffing"]
    assert result["confidence_score"] > 0.40


def test_fallback_engine_flag():
    """Test TF-IDF fallback identifies its source accurately without crashing."""
    result = categorize_complaint(
        "Hostel mess food quality issue",
        "Substandard food served in student canteen hostel.",
        allow_semantic=False
    )
    assert result["source"] == "AI - TF-IDF Fallback Engine"
    assert "explanation" in result
    assert len(result["explanation"]) > 10


def test_low_confidence_fallback():
    """Test text with no relevant educational domain vocabulary falls back to Other / Low Confidence."""
    result = categorize_complaint(
        "Random gibberish xqz ptqw",
        "Zzz blurp foobar qweasd 12345.",
        allow_semantic=False
    )
    assert result["category"] == "Other"
    assert result["confidence_level"] == "Low"


def test_keyword_extraction():
    """Test salient keyword extraction removes stopwords and highlights domain terms."""
    text = "The physics laboratory equipment and apparatus are not functioning for student experiments."
    keywords = extract_keywords(text)
    assert "the" not in keywords
    assert "for" not in keywords
    assert any(k in ["laboratory", "equipment", "apparatus", "experiments"] for k in keywords)
