"""
Profile discovery and parsing.

This is where a name on the approved roster (core.roster_discovery) finally
gets connected to a visible email. Nothing here is allowed to create a
Contact for a name that is not already on the roster — every path below is
driven by iterating roster entries, never by iterating arbitrary page
content.

Two sources of a verified email are supported, in preference order:
1. An individual profile page linked from a roster/department page
   ("Official personal profile").
2. The same directory card the roster entry was parsed from, when no
   separate profile page exists ("Faculty directory result").
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from core.crawler import fetch_html, new_session, polite_sleep
from core.domains import normalize_url, related_official_domain
from core.email_validation import (
    classify_email,
    extract_emails_with_context,
    is_admin_context,
    is_displayed_contact,
)
from core.faculty_validation import clean_name, clean_text, roster_name_match, valid_name
from core.models import Contact, PageLogEntry, Rejection, RejectionReason, RosterEntry
from core.roster_discovery import _CANDIDATE_NODE_SELECTOR, _extract_name_from_node, collect_names_in_node

PROFILE_HINTS = [
    "/profiles/", "/profile/", "/people/", "/faculty/",
    "cap.stanford.edu/profiles/view", "bio", "biography",
]

_PROFILE_EXCLUDE_HINTS = (
    "browse?", "/browse", "directory", "search", "name=",
    "org=", "department=", "page=", "filter=",
)

ROLE_TERMS = [
    "professor", "associate professor", "assistant professor",
    "clinical professor", "instructor", "lecturer",
    "chair", "chief", "faculty", "academic",
]


def looks_like_profile_url(url: str, link_text: str = "") -> bool:
    combined = f"{url} {link_text}".lower()
    if not any(hint in combined for hint in PROFILE_HINTS):
        return False
    if any(bad in combined for bad in _PROFILE_EXCLUDE_HINTS):
        return False
    return True


def discover_profile_links(
    page_html_cache: dict[str, str],
    official_host: str,
    roster_names: set[str],
) -> list[dict]:
    """
    Build a ranked list of individual-profile links found across the pages
    already crawled while building the roster. Links whose visible text
    matches an approved roster name are ranked highest.
    """
    links: dict[str, dict] = {}

    for page_url, html in page_html_cache.items():
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            target = normalize_url(urljoin(page_url, anchor.get("href", "")))
            text = clean_text(anchor.get_text(" ", strip=True))

            if not target or not related_official_domain(target, official_host):
                continue
            if not looks_like_profile_url(target, text):
                continue

            score = 20
            name_matches_roster = valid_name(text) and roster_name_match(text, roster_names)
            if name_matches_roster:
                score += 50
            elif valid_name(text):
                score += 20
            if any(term in f"{target} {text}".lower() for term in ROLE_TERMS):
                score += 10

            record = {
                "Profile URL": target,
                "Link Text": text,
                "Score": score,
                "Matches Roster Name": "Yes" if name_matches_roster else "No",
            }
            current = links.get(target)
            if not current or score > current["Score"]:
                links[target] = record

    return sorted(links.values(), key=lambda item: (-item["Score"], item["Profile URL"]))


def _parse_profile_page(
    url: str,
    html: str,
    official_host: str,
    roster_names: set[str],
    institution: str,
    department: str,
) -> tuple[list[Contact], list[Rejection]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "form"]):
        tag.decompose()

    page_text = clean_text(soup.get_text(" ", strip=True))

    name = None
    for selector in (
        "h1", '[itemprop="name"]', '[class*="profile-name" i]',
        '[class*="faculty-name" i]', '[class*="person-name" i]',
    ):
        for element in soup.select(selector):
            candidate = clean_name(element.get_text(" ", strip=True))
            if valid_name(candidate):
                name = candidate
                break
        if name:
            break

    if not name and soup.title:
        for part in re.split(r"\s+[|–—]\s+", clean_text(soup.title.get_text(" ", strip=True))):
            candidate = clean_name(part)
            if valid_name(candidate):
                name = candidate
                break

    if not name:
        return [], []

    if not roster_name_match(name, roster_names):
        return [], [Rejection(
            name=name,
            reason=RejectionReason.NOT_ON_ROSTER,
            source_url=url,
            detail="Profile page name does not match approved roster.",
        )]

    email_contexts = extract_emails_with_context(soup, page_text)

    contacts = []
    rejections = []
    accepted_any = False
    for email in sorted(email_contexts):
        occurrences = email_contexts[email]

        # An address labelled anywhere on the page as an administrative or
        # alternate contact belongs to an assistant, not to this faculty
        # member — attaching it here is exactly the misattribution the
        # spec forbids.
        if any(is_admin_context(entry["context"]) for entry in occurrences):
            rejections.append(Rejection(
                name=name,
                reason=RejectionReason.ADMIN_EMAIL,
                source_url=url,
                detail=email,
            ))
            continue

        # An address sitting in prose (typically a publication abstract)
        # belongs to that paper, lab or tool, not to this person.
        if not is_displayed_contact(occurrences):
            rejections.append(Rejection(
                name=name,
                reason=RejectionReason.NO_VISIBLE_EMAIL,
                source_url=url,
                detail=f"{email} — not a displayed contact field",
            ))
            continue

        is_valid, reason = classify_email(email, official_host)
        if is_valid:
            accepted_any = True
            contacts.append(Contact(
                name=name,
                email=email,
                institution=institution,
                department=department,
                faculty_title="",
                division_or_unit="",
                roster_source_url="",
                profile_source_url=url,
                extraction_method="Official personal profile",
            ))
        elif reason:
            rejections.append(Rejection(name=name, reason=reason, source_url=url, detail=email))

    if not accepted_any:
        rejections.append(Rejection(
            name=name,
            reason=RejectionReason.NO_VISIBLE_EMAIL,
            source_url=url,
        ))

    return contacts, rejections


def crawl_individual_profiles(
    profile_links: list[dict],
    official_host: str,
    roster_names: set[str],
    institution: str,
    department: str,
    max_profiles: int,
    delay_seconds: float,
) -> tuple[list[Contact], list[Rejection], list[PageLogEntry]]:
    session = new_session()
    contacts: list[Contact] = []
    rejections: list[Rejection] = []
    log: list[PageLogEntry] = []

    for index, profile in enumerate(profile_links[:max_profiles], start=1):
        profile_url = profile["Profile URL"]
        html, final_url = fetch_html(session, profile_url)

        if not html or not final_url:
            log.append(PageLogEntry(url=profile_url, status="Could not access"))
            continue
        if not related_official_domain(final_url, official_host):
            log.append(PageLogEntry(url=final_url, status="Rejected", detail="Outside official domain"))
            continue

        found_contacts, found_rejections = _parse_profile_page(
            final_url, html, official_host, roster_names, institution, department,
        )
        contacts.extend(found_contacts)
        rejections.extend(found_rejections)

        status = f"Verified contact found: {len(found_contacts)}" if found_contacts else "No verified faculty email"
        log.append(PageLogEntry(url=final_url, status=status))

        if delay_seconds > 0 and index < min(max_profiles, len(profile_links)):
            polite_sleep(delay_seconds)

    return contacts, rejections, log


# ---------------------------------------------------------------------------
# Card-level fallback: extract an email from the same directory card a
# roster entry was parsed from, when no separate profile page was found.
# ---------------------------------------------------------------------------

def extract_card_level_contacts(
    roster_entries: list[RosterEntry],
    page_html_cache: dict[str, str],
    official_host: str,
    institution: str,
    department: str,
    already_covered: set[str],
) -> tuple[list[Contact], list[Rejection]]:
    """
    For roster entries whose normalized_name is not already in
    `already_covered` (i.e. no profile-page contact was found for them),
    re-open the page they were parsed from and pull a visible email from
    their specific card only — never from unrelated cards on the same page.
    """
    from core.faculty_validation import normalize_person_name

    contacts: list[Contact] = []
    rejections: list[Rejection] = []

    pending = [entry for entry in roster_entries if entry.normalized_name not in already_covered]
    if not pending:
        return contacts, rejections

    by_page: dict[str, list[RosterEntry]] = {}
    for entry in pending:
        by_page.setdefault(entry.roster_source_url, []).append(entry)

    for page_url, entries in by_page.items():
        html = page_html_cache.get(page_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        wanted = {entry.normalized_name: entry for entry in entries}
        matched_names: set[str] = set()

        for node in soup.select(_CANDIDATE_NODE_SELECTOR):
            node_name = _extract_name_from_node(node)
            if not node_name:
                continue
            normalized = normalize_person_name(node_name)
            entry = wanted.get(normalized)
            if not entry or normalized in matched_names:
                continue

            block_text = clean_text(node.get_text(" ", strip=True))
            if is_admin_context(block_text):
                continue

            # A container holding more than one person is a list, not a
            # card. Pairing its first name with its first email misattributes
            # the address, so skip it and let a tighter container match.
            if len(collect_names_in_node(node)) != 1:
                continue

            card_contexts = extract_emails_with_context(node, block_text)
            if not card_contexts:
                continue

            matched_names.add(normalized)
            found_valid = False
            for email in sorted(card_contexts):
                occurrences = card_contexts[email]
                if any(is_admin_context(item["context"]) for item in occurrences):
                    rejections.append(Rejection(
                        name=entry.name,
                        reason=RejectionReason.ADMIN_EMAIL,
                        source_url=page_url,
                        detail=email,
                    ))
                    continue
                if not is_displayed_contact(occurrences):
                    rejections.append(Rejection(
                        name=entry.name,
                        reason=RejectionReason.NO_VISIBLE_EMAIL,
                        source_url=page_url,
                        detail=f"{email} — not a displayed contact field",
                    ))
                    continue
                is_valid, reason = classify_email(email, official_host)
                if is_valid:
                    found_valid = True
                    contacts.append(Contact(
                        name=entry.name,
                        email=email,
                        institution=institution,
                        department=department,
                        faculty_title=entry.title,
                        division_or_unit=entry.division,
                        roster_source_url=entry.roster_source_url,
                        profile_source_url="",
                        extraction_method="Faculty directory result",
                    ))
                elif reason:
                    rejections.append(Rejection(name=entry.name, reason=reason, source_url=page_url, detail=email))
            if not found_valid:
                rejections.append(Rejection(
                    name=entry.name,
                    reason=RejectionReason.NO_VISIBLE_EMAIL,
                    source_url=page_url,
                ))

        for entry in entries:
            if entry.normalized_name not in matched_names:
                rejections.append(Rejection(
                    name=entry.name,
                    reason=RejectionReason.NO_VISIBLE_EMAIL,
                    source_url=page_url,
                ))

    return contacts, rejections
