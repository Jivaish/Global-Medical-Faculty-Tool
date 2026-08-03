"""
Shared data structures used across every module.

Keeping these in one place means department_discovery, roster_discovery,
email_validation, deduplication and app.py all agree on field names, and the
final CSV columns can be generated directly from RosterContact.as_row().
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Discovery-stage records
# ---------------------------------------------------------------------------

@dataclass
class DepartmentCandidate:
    """A URL that plausibly belongs to the selected department."""

    url: str
    title: str
    matched_terms: list[str]
    discovery_source: str          # homepage_link | sitemap | nested_sitemap | common_path | adapter
    score: int

    def as_row(self) -> dict:
        return {
            "Department URL": self.url,
            "Title / Link Text": self.title,
            "Matched Specialty Terms": ", ".join(self.matched_terms[:8]),
            "Discovery Source": self.discovery_source,
            "Score": self.score,
        }


@dataclass
class RosterEntry:
    """
    One approved faculty member, built BEFORE any email is looked at.

    This is the roster-first contract: nothing downstream may produce a
    Contact unless it can point back to a RosterEntry with matching
    normalized_name.
    """

    name: str
    normalized_name: str
    title: str
    division: str
    roster_source_url: str
    evidence: str = ""
    profile_url: str | None = None

    def as_row(self) -> dict:
        return {
            "Name": self.name,
            "Faculty Title": self.title,
            "Division or Unit": self.division,
            "Faculty Roster Source URL": self.roster_source_url,
            "Profile URL": self.profile_url or "",
            "Evidence": self.evidence[:300],
        }


# ---------------------------------------------------------------------------
# Contact / rejection records
# ---------------------------------------------------------------------------

# Preference order used by deduplication.py — lower number wins.
SOURCE_STRENGTH = {
    "Official personal profile": 0,
    "Faculty directory result": 1,
    "Directory card": 1,
    "Department page": 2,
    "Local page block": 2,
    "Department fallback": 9,
}


@dataclass
class Contact:
    """A verified faculty contact: approved roster entry + a visible email."""

    name: str
    email: str
    institution: str
    department: str
    faculty_title: str
    division_or_unit: str
    roster_source_url: str
    profile_source_url: str
    extraction_method: str
    verification_status: str = "Verified — matches approved faculty roster"

    def as_row(self) -> dict:
        return {
            "Name": self.name,
            "Email": self.email,
            "Institution": self.institution,
            "Department": self.department,
            "Faculty Title": self.faculty_title,
            "Division or Unit": self.division_or_unit,
            "Faculty Roster Source URL": self.roster_source_url,
            "Profile Source URL": self.profile_source_url,
            "Extraction Method": self.extraction_method,
            "Verification Status": self.verification_status,
        }

    def source_strength(self) -> int:
        return SOURCE_STRENGTH.get(self.extraction_method, 5)

    def dedup_email_key(self) -> str:
        return self.email.strip().lower()

    def dedup_name_key(self) -> str:
        return f"{self.name.strip().casefold()}|{self.institution.strip().casefold()}|{self.department.strip().casefold()}"


# Fixed rejection-reason vocabulary. app.py and roster_discovery /
# email_validation should only ever use one of these strings so the audit
# table stays consistent instead of free-text.
class RejectionReason:
    NOT_ON_ROSTER = "Not on official faculty roster"
    STAFF_ROLE = "Staff role"
    RESIDENT = "Resident"
    FELLOW = "Fellow"
    STUDENT = "Student"
    EMERITUS = "Emeritus"
    ADJUNCT = "Adjunct"
    AFFILIATED = "Affiliated faculty"
    ADMIN_EMAIL = "Administrative email"
    GENERIC_EMAIL = "Generic email"
    PERSONAL_DOMAIN = "Personal email domain"
    DEPARTMENT_MISMATCH = "Department mismatch"
    NO_VISIBLE_EMAIL = "No visible institutional email"
    OUTSIDE_DOMAIN = "Outside official domain"
    UNREADABLE_PAGE = "Page could not be accessed"
    NAME_INVALID = "Not a recognizable person name"


@dataclass
class Rejection:
    name: str
    reason: str
    source_url: str = ""
    detail: str = ""

    def as_row(self) -> dict:
        return {
            "Name": self.name,
            "Rejection Reason": self.reason,
            "Source URL": self.source_url,
            "Detail": self.detail,
        }


@dataclass
class RunSummary:
    department_candidates_found: int = 0
    faculty_roster_entries_found: int = 0
    profiles_inspected: int = 0
    verified_personal_emails: int = 0
    records_rejected: int = 0
    faculty_with_no_public_email: int = 0
    generic_fallback_used: bool = False

    def as_dict(self) -> dict:
        return {
            "Department candidates found": self.department_candidates_found,
            "Faculty roster entries found": self.faculty_roster_entries_found,
            "Profiles inspected": self.profiles_inspected,
            "Verified personal faculty emails": self.verified_personal_emails,
            "Records rejected": self.records_rejected,
            "Faculty with no public email": self.faculty_with_no_public_email,
            "Generic fallback used": "Yes" if self.generic_fallback_used else "No",
        }


@dataclass
class PageLogEntry:
    url: str
    status: str
    detail: str = ""

    def as_row(self) -> dict:
        return {"URL": self.url, "Status": self.status, "Detail": self.detail}


CSV_COLUMNS = [
    "Name",
    "Email",
    "Institution",
    "Department",
    "Faculty Title",
    "Division or Unit",
    "Faculty Roster Source URL",
    "Profile Source URL",
    "Extraction Method",
    "Verification Status",
]
