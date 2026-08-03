"""
Email extraction and validation.

Only a personal institutional email that is VISIBLY DISPLAYED on an official
page is ever accepted (mailto: link or plain text on the page, including
common obfuscation patterns like "name [at] domain [dot] edu"). Nothing here
ever constructs or guesses an address from a person's name.
"""

from __future__ import annotations

import re

from bs4 import Tag

from core.domains import organization_root
from core.faculty_validation import clean_text

EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,63}\b",
    re.IGNORECASE,
)

GENERIC_EMAIL_PREFIXES = {
    "info", "contact", "admin", "office", "support", "help",
    "appointments", "appointment", "clinic", "department", "dept",
    "faculty", "reception", "admissions", "webmaster", "media",
    "communications", "education", "research", "enquiries", "inquiries",
    "frontdesk", "secretary", "generalinfo", "hello",
}

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "aol.com", "protonmail.com", "proton.me",
    "live.com", "msn.com", "mail.com",
}

_ADMIN_CONTEXT_MARKERS = (
    "administrative contact", "administrative associate",
    "administrative assistant", "administrative aide",
    "executive assistant", "alternate contact",
    "program coordinator", "program manager", "office manager",
    "assistant to the", "scheduling", "scheduler",
    "media inquiries", "press inquiries", "for appointments",
)

# How much text immediately preceding an email counts as its "label".
# Stanford profiles render assistants as
# "Contact | Alternate Contact | <Name> | Administrative Assistant | <email>",
# so the marker sits within a couple hundred characters before the address.
EMAIL_CONTEXT_WINDOW = 220

_OBFUSCATION_REPLACEMENTS = [
    (r"\s*\[\s*at\s*\]\s*", "@"),
    (r"\s*\(\s*at\s*\)\s*", "@"),
    (r"\s+at\s+", "@"),
    (r"\s*\[\s*dot\s*\]\s*", "."),
    (r"\s*\(\s*dot\s*\)\s*", "."),
    (r"\s+dot\s+", "."),
]


def decode_visible_emails(text: str) -> set[str]:
    """
    Extract plain emails plus common visible-obfuscation patterns
    ("name [at] domain [dot] edu"). This only decodes text that is already
    visibly on the page — it never fabricates an address.
    """
    values = set(EMAIL_RE.findall(text or ""))
    candidate = clean_text(text or "")
    for pattern, replacement in _OBFUSCATION_REPLACEMENTS:
        candidate = re.sub(pattern, replacement, candidate, flags=re.I)
    values.update(EMAIL_RE.findall(candidate))
    return {value.lower().strip(".,;:()[]<>") for value in values}


def domain_belongs_to_institution(email_domain: str, official_host: str) -> bool:
    """
    True if the email's domain is the official host, a subdomain of it, or
    shares the same organization root (mirrors core.domains.related_official
    _domain so email acceptance and page-crawl acceptance never disagree).
    """
    email_domain = email_domain.lower()
    official_host = official_host.lower()
    return (
        email_domain == official_host
        or email_domain.endswith("." + official_host)
        or official_host.endswith("." + email_domain)
        or organization_root(email_domain) == organization_root(official_host)
    )


def classify_email(email: str, official_host: str) -> tuple[bool, str | None]:
    """
    Returns (is_valid, rejection_reason). rejection_reason is one of
    core.models.RejectionReason's string constants when invalid.
    """
    from core.models import RejectionReason

    email = email.lower().strip(".,;:()[]<>")
    if not EMAIL_RE.fullmatch(email):
        return False, RejectionReason.NO_VISIBLE_EMAIL

    local, domain = email.split("@", 1)
    compact_local = re.sub(r"[^a-z0-9]", "", local)

    if domain in PERSONAL_EMAIL_DOMAINS:
        return False, RejectionReason.PERSONAL_DOMAIN
    if compact_local in GENERIC_EMAIL_PREFIXES:
        return False, RejectionReason.GENERIC_EMAIL
    if not domain_belongs_to_institution(domain, official_host):
        return False, RejectionReason.OUTSIDE_DOMAIN
    return True, None


def valid_email(email: str, official_host: str) -> bool:
    is_valid, _ = classify_email(email, official_host)
    return is_valid


def is_admin_context(text: str) -> bool:
    lowered = clean_text(text).lower()
    if "contact academic" in lowered:
        return False
    return any(marker in lowered for marker in _ADMIN_CONTEXT_MARKERS)


def emails_in_block(block: Tag, block_text: str) -> set[str]:
    """Collect visible emails from a card/block: mailto hrefs + link text + block text."""
    emails: set[str] = set()
    for anchor in block.select('a[href^="mailto:" i]'):
        href = anchor.get("href", "")
        emails.update(decode_visible_emails(f"{href} {anchor.get_text(' ', strip=True)}"))
    emails.update(decode_visible_emails(block_text))
    return emails


def _ancestor_context(anchor: Tag, max_levels: int = 4, max_chars: int = 400) -> str:
    """Text of the nearest meaningful ancestor, used as a mailto link's label."""
    current = anchor
    for _ in range(max_levels):
        parent = current.parent
        if not isinstance(parent, Tag):
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        if len(text) >= 40:
            return text[:max_chars]
    return clean_text(current.get_text(" ", strip=True))[:max_chars]


# An email is only a *displayed contact* if it is a real mailto link or sits
# behind an explicit label. Addresses that merely appear in prose — most
# often inside a publication abstract — belong to a paper, a lab or a tool,
# not to the person whose profile is being read.
_CONTACT_LABEL_RE = re.compile(
    r"(?:e-?mail|contact|reach(?:\s+\w+)?\s+at|correspondence)\W{0,12}$",
    re.IGNORECASE,
)
_CONTACT_LABEL_WINDOW = 40


def _trim_sentence_run_on(matched: str) -> str:
    """
    Drop a trailing label glued on by missing whitespace, e.g.
    "naghaeep@stanford.edu.Supplementary" -> "naghaeep@stanford.edu".
    A capitalised final label is prose, not a TLD.
    """
    local, _, domain = matched.partition("@")
    labels = domain.split(".")
    while len(labels) > 2 and labels[-1][:1].isupper():
        labels.pop()
    return f"{local}@{'.'.join(labels)}"


def is_contact_labeled(context: str) -> bool:
    """True if the text right before the address explicitly labels it as one."""
    return bool(_CONTACT_LABEL_RE.search(clean_text(context)))


def extract_emails_with_context(soup, page_text: str) -> dict[str, list[dict]]:
    """
    Map each visible email to every occurrence of it, recording the
    surrounding text and whether it came from a mailto link or plain text.

    Attribution matters more than recall here. Returning all occurrences
    lets the caller (a) reject an address outright when ANY occurrence is
    labelled as an administrative/alternate contact, and (b) require at
    least one occurrence to be a genuine displayed contact.
    """
    occurrences: dict[str, list[dict]] = {}

    def add(email: str, context: str, source: str) -> None:
        if not email:
            return
        occurrences.setdefault(email, []).append({"context": context, "source": source})

    for anchor in soup.select('a[href^="mailto:" i]'):
        href = anchor.get("href", "")
        # "mailto:?subject=..." share widgets carry no recipient.
        address_part = href[7:].split("?", 1)[0].strip()
        if not address_part:
            continue
        found = decode_visible_emails(f"{address_part} {anchor.get_text(' ', strip=True)}")
        context = _ancestor_context(anchor)
        for email in found:
            add(email, context, "mailto")

    for match in EMAIL_RE.finditer(page_text or ""):
        raw = _trim_sentence_run_on(match.group(0))
        email = raw.lower().strip(".,;:()[]<>")
        start = max(0, match.start() - EMAIL_CONTEXT_WINDOW)
        add(email, page_text[start:match.end()], "text")

    return occurrences


def is_displayed_contact(entries: list[dict]) -> bool:
    """
    True if at least one occurrence is a real displayed contact: a mailto
    link, or plain text immediately preceded by an "Email:"/"Contact:" label.
    """
    for entry in entries:
        if entry["source"] == "mailto":
            return True
        # Only the text preceding the address counts as its label, so drop
        # the address's own local part before looking for one.
        before = entry["context"].rsplit("@", 1)[0]
        before = before.rsplit(" ", 1)[0] if " " in before else ""
        if is_contact_labeled(before[-_CONTACT_LABEL_WINDOW:]):
            return True
    return False
