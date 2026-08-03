"""
Generic department-contact fallback.

Only triggers when the department and faculty roster were verified (i.e.
roster is non-empty) but zero personal faculty emails were publicly visible
anywhere. Returns at most one row, labeled "Department Contact" — never one
per faculty member.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from core.crawler import fetch_html, new_session
from core.email_validation import GENERIC_EMAIL_PREFIXES, decode_visible_emails
from core.faculty_validation import clean_text
from core.models import Contact

# Department-level mailbox names that are generic even though they are not
# in the general-purpose prefix list (e.g. medicine@, nursing@, obgyn@).
_DEPARTMENT_MAILBOX_WORDS = {
    "medicine", "med", "nursing", "health", "school", "college",
    "dept", "department", "departments", "faculty", "academics",
    "academic", "enquiry", "general", "mail",
}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def is_generic_department_local(local: str, terms: list[str]) -> bool:
    """
    A mailbox is a department contact if its name is a general-purpose
    prefix, a department-level word, or the selected specialty itself
    (obgyn@, pediatrics@, nursing@).
    """
    compact = _compact(local)
    if compact in GENERIC_EMAIL_PREFIXES or compact in _DEPARTMENT_MAILBOX_WORDS:
        return True
    return any(_compact(term) == compact for term in terms)


def find_generic_department_email(
    department_urls: list[str],
    official_host: str,
    terms: list[str],
) -> tuple[str, str] | None:
    """Returns (email, source_url) for the first verified generic mailbox found, or None."""
    session = new_session()
    for url in department_urls:
        html, final_url = fetch_html(session, url)
        if not html or not final_url:
            continue
        soup = BeautifulSoup(html, "html.parser")
        text = clean_text(soup.get_text(" ", strip=True))
        if not any(term in text.lower() for term in terms):
            continue

        emails = set()
        for anchor in soup.select('a[href^="mailto:" i]'):
            href = anchor.get("href", "")
            emails.update(decode_visible_emails(f"{href} {anchor.get_text(' ', strip=True)}"))
        emails.update(decode_visible_emails(text))

        for email in sorted(emails):
            if "@" not in email:
                continue
            local, domain = email.split("@", 1)
            if is_generic_department_local(local, terms) and (
                domain == official_host or domain.endswith("." + official_host)
            ):
                return email, final_url
    return None


def build_fallback_contact(
    email: str,
    source_url: str,
    institution: str,
    department: str,
) -> Contact:
    return Contact(
        name="Department Contact",
        email=email,
        institution=institution,
        department=department,
        faculty_title="",
        division_or_unit="",
        roster_source_url=source_url,
        profile_source_url="",
        extraction_method="Department fallback",
        verification_status="No public personal faculty email found",
    )
