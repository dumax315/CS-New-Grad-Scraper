import pytest

from app.source_scope import classify_direct_candidate


@pytest.mark.parametrize(
    ("title", "description", "code"),
    [
        (
            "Software Engineer, Class of 2027",
            "Start in summer 2027.",
            "include_explicit",
        ),
        (
            "Software Engineer, University Graduate",
            "Join our early career engineering team.",
            "include_explicit",
        ),
        (
            "Software Engineer I",
            "University candidates with 0-1 years of experience are welcome.",
            "include_plausible",
        ),
        ("Software Engineering Intern", "Summer role.", "exclude_internship"),
        ("Senior Backend Engineer", "Build APIs.", "exclude_seniority"),
        (
            "Backend Engineer",
            "Requires 3+ years of professional experience.",
            "exclude_experience",
        ),
        (
            "Software Engineer, Class of 2026",
            "New graduate role.",
            "exclude_timing",
        ),
        ("Product Manager, New Grad", "University role.", "exclude_non_engineering"),
        ("Software Engineer", "Build reliable services.", "exclude_unknown"),
    ],
)
def test_direct_scope_classifier_is_explainable(title, description, code):
    result = classify_direct_candidate(title, description)

    assert result.code == code
    assert result.reason


def test_only_explicit_2027_timing_sets_timing_evidence():
    assert classify_direct_candidate(
        "Software Engineer, Class of 2027",
    ).timing_explicit is True
    assert classify_direct_candidate(
        "Software Engineer, University Graduate",
    ).timing_explicit is False
