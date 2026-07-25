"""Explainable deterministic scope gate for direct employer boards."""

from collections import Counter
from dataclasses import dataclass, replace
import re
from typing import Literal

from app.source_types import Candidate

ScopeCode = Literal[
    "include_explicit",
    "include_plausible",
    "exclude_internship",
    "exclude_seniority",
    "exclude_experience",
    "exclude_timing",
    "exclude_non_engineering",
    "exclude_unknown",
]

INTERNSHIP_RE = re.compile(r"\b(intern(?:ship)?|co-?op|apprentice(?:ship)?)\b", re.I)
SENIORITY_RE = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head)\b", re.I)
NON_ENGINEERING_RE = re.compile(
    r"\b(quant(?:itative)?\s+trader|trader|product manager|\bpm\b|recruiter|sales|marketing)\b",
    re.I,
)
ENGINEERING_RE = re.compile(
    r"\b(software|swe|developer|engineer|sdet|devops|site reliability|platform|"
    r"machine learning|data engineer|backend|frontend|full[ -]?stack|infrastructure|security)\b",
    re.I,
)
NEW_GRAD_RE = re.compile(
    r"\b(new grad(?:uate)?|university grad(?:uate)?|graduate engineer|early career|campus hire)\b",
    re.I,
)
CLASS_YEAR_RE = re.compile(r"\bclass of (20\d{2})\b", re.I)
EXPLICIT_2027_RE = re.compile(
    r"\b(class of 2027|spring 2027|summer 2027|fall 2027|2027 start|start(?:ing)? in 2027)\b",
    re.I,
)
EARLIER_TIMING_RE = re.compile(
    r"\b(class of 202[4-6]|spring 202[4-6]|summer 202[4-6]|fall 202[4-6]|202[4-6] start)\b",
    re.I,
)
MULTI_YEAR_REQUIREMENT_RE = re.compile(
    r"\b(?:minimum(?: of)?|at least|requires?|must have)\s+"
    r"(?:[2-9]|\d{2,})(?:\+|-[0-9]+)?\s+years?\b",
    re.I,
)
ZERO_ONE_YEAR_RE = re.compile(
    r"\b(?:0\s*(?:-|to)\s*1|zero\s*(?:-|to)\s*one|up to 1)\s+years?\b",
    re.I,
)
ENTRY_TITLE_RE = re.compile(
    r"\b(junior|entry[ -]?level|engineer i|developer i|associate engineer)\b",
    re.I,
)


@dataclass(frozen=True)
class ScopeResult:
    code: ScopeCode
    reason: str
    timing_explicit: bool = False

    @property
    def included(self) -> bool:
        return self.code.startswith("include_")


def classify_direct_candidate(title: str, description: str = "") -> ScopeResult:
    combined = f"{title}\n{description}"
    if INTERNSHIP_RE.search(combined):
        return ScopeResult("exclude_internship", "internship, co-op, or apprenticeship wording")
    if NON_ENGINEERING_RE.search(title):
        return ScopeResult("exclude_non_engineering", "excluded role family")
    if not ENGINEERING_RE.search(title):
        return ScopeResult("exclude_non_engineering", "title lacks an engineering role signal")
    if SENIORITY_RE.search(title):
        return ScopeResult("exclude_seniority", "senior-level title")
    if MULTI_YEAR_REQUIREMENT_RE.search(combined):
        return ScopeResult("exclude_experience", "requires multiple years of experience")

    has_2027 = bool(EXPLICIT_2027_RE.search(combined))
    mentioned_class_years = {int(year) for year in CLASS_YEAR_RE.findall(combined)}
    if (EARLIER_TIMING_RE.search(combined) or mentioned_class_years) and not (
        has_2027 or 2027 in mentioned_class_years
    ):
        return ScopeResult("exclude_timing", "explicit timing targets an earlier graduating class")
    if has_2027 or 2027 in mentioned_class_years:
        return ScopeResult(
            "include_explicit",
            "explicit Spring/Class of 2027 timing",
            timing_explicit=True,
        )
    if NEW_GRAD_RE.search(combined):
        return ScopeResult("include_explicit", "explicit new-grad or university hiring wording")
    if ENTRY_TITLE_RE.search(title) and (
        ZERO_ONE_YEAR_RE.search(combined) or "university" in combined.lower()
    ):
        return ScopeResult("include_plausible", "entry-level title with zero-to-one-year or university evidence")
    return ScopeResult("exclude_unknown", "no explicit new-grad or supported entry-level evidence")


def scope_direct_candidates(
    candidates: list[Candidate],
    *,
    malformed_count: int = 0,
) -> tuple[tuple[Candidate, ...], tuple[tuple[str, int], ...]]:
    accepted: list[Candidate] = []
    counts: Counter[str] = Counter()
    if malformed_count:
        counts["exclude_unknown"] += malformed_count
    for candidate in candidates:
        result = classify_direct_candidate(candidate.title, candidate.description_text)
        if result.included:
            accepted.append(replace(
                candidate,
                scope_decision=result.code,
                timing_explicit=result.timing_explicit,
            ))
        else:
            counts[result.code] += 1
    return tuple(accepted), tuple(sorted(counts.items()))
