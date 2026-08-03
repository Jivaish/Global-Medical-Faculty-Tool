"""
Faculty-role and name validation.

Two concrete bugs in the prior version lived here and are fixed explicitly:

1. Title/role matching used plain substring checks (`"staff" in text`),
   which rejected a professor named "Stafford" (`"staff" in "stafford"`).
   Every check below uses \\b-bounded regex against whole words/phrases.
2. "fellow" was an unconditional exclusion, so a bio reading "Fellow of the
   American College of Obstetricians and Gynecologists" (a routine
   credential, not a job title) silently dropped an attending professor.
   EXCLUDED_ROLE_PATTERNS below only match "fellow" as a role/position
   (e.g. "Clinical Fellow", "Fellow, Maternal-Fetal Medicine", "Postdoctoral
   Fellow") and explicitly ignore "Fellow of the ..." credential phrasing.
"""

from __future__ import annotations

import re

from core.models import RejectionReason


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


CREDENTIALS = (
    "MD", "DO", "PHD", "DPHIL", "MPH", "MSC", "MS", "MA", "MBBS", "MBCHB",
    "DNP", "RN", "MSN", "FACOG", "FRCOG", "FACS", "FAAP", "MBA", "JD",
    "PHARMD", "DDS", "DMD", "DVM", "SCD", "EDD", "BSN", "CNM", "MHA",
    "FACC", "FRCP", "FRCS", "MRCP", "MPHIL", "BA", "BS", "HCLD", "MED",
    "MSEd", "FACP", "MBBCH", "DSC", "RD", "LCSW", "NP", "PA",
)
_CREDENTIAL_SET = {credential.upper() for credential in CREDENTIALS}


def _strip_credential_suffixes(value: str) -> str:
    """
    Drop trailing degree/credential chunks, tolerating dotted spellings
    ("M.D.", "Ph.D.", "H.C.L.D.") that a plain word-boundary regex misses.
    """
    parts = [part.strip() for part in value.split(",")]
    while len(parts) > 1:
        tail = re.sub(r"[^A-Za-z]", "", parts[-1]).upper()
        if tail and tail in _CREDENTIAL_SET:
            parts.pop()
        else:
            break
    return ", ".join(parts)


def clean_name(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"^(?:Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+[|–—]\s+.*$", "", value)
    value = _strip_credential_suffixes(value)
    return value.strip(" ,;|-–—")


# Name particles that legitimately appear lowercase inside a person's name.
_NAME_PARTICLES = {
    "de", "del", "della", "da", "di", "van", "von", "der", "den",
    "bin", "binte", "al", "el", "la", "le", "dos", "das", "du",
    "ter", "ten", "st", "mc", "mac", "y", "ibn",
}

# Whole tokens that mean "this string is a page heading or org unit, not a
# person". Checked per-token so a surname is never matched by substring.
_NAME_STOPWORDS = {
    "and", "the", "for", "of", "our", "all", "view", "more", "home",
    "current", "research", "scholarly", "interests", "education",
    "contact", "alternate", "additional", "info", "information",
    "office", "department", "departments", "faculty", "staff", "people",
    "directory", "profile", "profiles", "provider", "providers",
    "school", "college", "university", "institute", "center", "centre",
    "division", "divisions", "section", "program", "programs",
    "affairs", "relations", "provost", "dean", "admissions", "business",
    "medicine", "health", "hospital", "clinic", "laboratory", "lab",
    "news", "events", "about", "overview", "publications", "biography",
    "administrative", "assistant", "coordinator", "manager", "team",
    "student", "students", "alumni", "giving", "search", "menu",
    "clinical", "trials", "care", "patient", "patients", "services",
}

# Kept for phrase-level blocking (e.g. "our team") that token checks miss.
_NAME_BLOCK_RE = re.compile(r"\b(?:our team|et al)\b", re.IGNORECASE)

_NAME_TOKEN_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+$")


def valid_name(value: str) -> bool:
    """
    Token-based person-name check.

    The previous implementation compiled its capitalization rule with
    re.IGNORECASE, which silently disabled that very rule — so page headings
    like "Current Research and Scholarly Interests" validated as names. Each
    token is now checked explicitly for capitalization and against a
    whole-word stopword set.
    """
    name = clean_name(value)
    if not 4 <= len(name) <= 90:
        return False
    if "@" in name or any(char.isdigit() for char in name):
        return False
    if _NAME_BLOCK_RE.search(name):
        return False

    tokens = [token for token in name.replace(",", " ").split() if token]
    if not 2 <= len(tokens) <= 6:
        return False

    strong_tokens = 0
    for token in tokens:
        core = token.strip(".,'’-")
        if not core:
            return False
        lowered = core.lower()
        if lowered in _NAME_PARTICLES:
            continue
        if lowered in _NAME_STOPWORDS:
            return False
        if not core[0].isupper():
            return False
        if not _NAME_TOKEN_RE.match(core):
            return False
        strong_tokens += 1

    return strong_tokens >= 2


def normalize_person_name(name: str) -> str:
    value = clean_name(name)
    value = re.sub(
        r"\b(?:MD|DO|PhD|MPH|MSc|MS|MBBS|MBChB|FACOG|FRCOG)\b\.?",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+", " ", value)
    return clean_text(value).casefold()


# ---------------------------------------------------------------------------
# Title / role gating
# ---------------------------------------------------------------------------

# INCLUDE ONLY these current-academic-faculty titles.
ALLOWED_TITLE_PATTERNS = [
    r"\bclinical\s+associate\s+professor\b",
    r"\bclinical\s+assistant\s+professor\b",
    r"\bclinical\s+professor\b",
    r"\bassociate\s+professor\b",
    r"\bassistant\s+professor\b",
    r"\bprofessor\b",
    r"\bclinical\s+instructor\b",
    r"\binstructor\b",
    r"\blecturer\b",
    r"\bdepartment\s+chair\b",
    r"\bdivision\s+chief\b",
    r"\bchair(?:person)?\s+of\s+(?:the\s+)?department\b",
]

# EXCLUDE these roles outright — checked first, and wins over an allowed
# title match (e.g. "Adjunct Clinical Professor" is still excluded).
#
# Each pattern targets the ROLE usage, not credential mentions, so bios like
# "Fellow of the American College of Obstetricians and Gynecologists" or a
# surname such as "Stafford" are never caught by these patterns.
EXCLUDED_ROLE_PATTERNS = [
    r"\bemeritus\b",
    r"\bemerita\b",
    r"\badjunct\b",
    r"\baffiliated\s+faculty\b",
    r"\bcourtesy\s+faculty\b",
    r"\bvisiting\s+(?:faculty|professor|scholar)\b",
    r"\bresident\b",
    r"\b(?:clinical\s+|postdoctoral\s+|research\s+)?fellow\b"
    r"(?!\s+of\s+the\s+(?:American|Royal|National|International)\b)",
    r"\bfellowship\b",
    r"\bpostdoctoral\b",
    r"\bpostdoc\b",
    r"\bresearch\s+assistant\b",
    r"\bresearch\s+coordinator\b",
    r"\bprogram\s+manager\b",
    r"\bcoordinator\b",
    r"\badministrative\s+assistant\b",
    r"\badministrative\s+associate\b",
    r"\bexecutive\s+assistant\b",
    r"\bnurse\s+practitioner\b",
    r"\bphysician\s+assistant\b",
    r"\bmidwife\b",
    r"\bstudent\b",
    r"\balternate\s+(?:administrative\s+)?contact\b",
]

_ALLOWED_RE = [re.compile(p, re.IGNORECASE) for p in ALLOWED_TITLE_PATTERNS]
_EXCLUDED_RE = [re.compile(p, re.IGNORECASE) for p in EXCLUDED_ROLE_PATTERNS]

# Maps an excluded pattern index range to a specific RejectionReason so the
# audit table can say *why*, not just "not on roster".
_EXCLUSION_REASON_BY_PATTERN: list[tuple[str, str]] = [
    (r"\bemeritus\b", RejectionReason.EMERITUS),
    (r"\bemerita\b", RejectionReason.EMERITUS),
    (r"\badjunct\b", RejectionReason.ADJUNCT),
    (r"\baffiliated\s+faculty\b", RejectionReason.AFFILIATED),
    (r"\bcourtesy\s+faculty\b", RejectionReason.AFFILIATED),
    (r"\bvisiting\s+(?:faculty|professor|scholar)\b", RejectionReason.AFFILIATED),
    (r"\bresident\b", RejectionReason.RESIDENT),
    (
        r"\b(?:clinical\s+|postdoctoral\s+|research\s+)?fellow\b"
        r"(?!\s+of\s+the\s+(?:American|Royal|National|International)\b)",
        RejectionReason.FELLOW,
    ),
    (r"\bfellowship\b", RejectionReason.FELLOW),
    (r"\bpostdoctoral\b", RejectionReason.FELLOW),
    (r"\bpostdoc\b", RejectionReason.FELLOW),
    (r"\bresearch\s+assistant\b", RejectionReason.STAFF_ROLE),
    (r"\bresearch\s+coordinator\b", RejectionReason.STAFF_ROLE),
    (r"\bprogram\s+manager\b", RejectionReason.STAFF_ROLE),
    (r"\bcoordinator\b", RejectionReason.STAFF_ROLE),
    (r"\badministrative\s+assistant\b", RejectionReason.STAFF_ROLE),
    (r"\badministrative\s+associate\b", RejectionReason.STAFF_ROLE),
    (r"\bexecutive\s+assistant\b", RejectionReason.STAFF_ROLE),
    (r"\bnurse\s+practitioner\b", RejectionReason.STAFF_ROLE),
    (r"\bphysician\s+assistant\b", RejectionReason.STAFF_ROLE),
    (r"\bmidwife\b", RejectionReason.STAFF_ROLE),
    (r"\bstudent\b", RejectionReason.STUDENT),
    (r"\balternate\s+(?:administrative\s+)?contact\b", RejectionReason.STAFF_ROLE),
]
_EXCLUSION_REASON_RE = [(re.compile(p, re.IGNORECASE), reason) for p, reason in _EXCLUSION_REASON_BY_PATTERN]


def excluded_role_reason(text: str) -> str | None:
    """Return the specific RejectionReason if text names an excluded role, else None."""
    lowered = clean_text(text)
    for pattern, reason in _EXCLUSION_REASON_RE:
        if pattern.search(lowered):
            return reason
    return None


def matched_allowed_title(text: str) -> str | None:
    """Return the matched allowed-title phrase (for display), or None."""
    lowered = clean_text(text)
    for pattern in _ALLOWED_RE:
        match = pattern.search(lowered)
        if match:
            return match.group(0).strip()
    return None


def is_allowed_faculty_title(text: str) -> bool:
    if excluded_role_reason(text):
        return False
    return matched_allowed_title(text) is not None


def roster_name_match(name: str, roster_names: set[str]) -> bool:
    """
    Exact normalized match first; falls back to first+last token match so
    "Dr. Jane A. Smith, MD" on a profile page still matches a roster entry
    stored as "Jane Smith".
    """
    normalized = normalize_person_name(name)
    if normalized in roster_names:
        return True

    parts = normalized.split()
    if len(parts) >= 2:
        first_last = f"{parts[0]} {parts[-1]}"
        for roster_name in roster_names:
            roster_parts = roster_name.split()
            if len(roster_parts) >= 2 and first_last == f"{roster_parts[0]} {roster_parts[-1]}":
                return True
    return False
