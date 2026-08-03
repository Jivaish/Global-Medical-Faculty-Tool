"""
Faculty-roster-first discovery.

This is the module that makes the whole app "roster-first": it builds the
approved list of (name, title, division, source) BEFORE any email is looked
at anywhere in the pipeline. email_validation / profile_discovery are only
ever allowed to attach an email to a name that already exists in the roster
this module returns.

Crawling here supports pagination (rel="next", numbered page links) and
follows same-domain links that look like faculty/department pages, mirroring
how the previous single-file version discovered faculty pages — but without
extracting any contact/email data along the way.
"""

from __future__ import annotations

import re
from collections import deque
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from core.crawler import VisitedPages, fetch_html, find_pagination_links, new_session, polite_sleep
from core.department_discovery import FACULTY_TERMS
from core.domains import host_of, normalize_url, related_official_domain
from core.faculty_validation import (
    clean_name,
    clean_text,
    excluded_role_reason,
    matched_allowed_title,
    normalize_person_name,
    valid_name,
)
from core.models import Rejection, RosterEntry

_CANDIDATE_NODE_SELECTOR = (
    "article, li, tr, [class*='faculty' i], [class*='person' i], "
    "[class*='profile' i], [class*='staff' i], [class*='card' i], "
    "[class*='result' i]"
)

_DIVISION_SELECTORS = ('[class*="division" i]', '[class*="department" i]', '[class*="unit" i]')
_DIVISION_TEXT_RE = re.compile(
    r"(Division|Section|Unit) of [A-Za-z,&/\-\s]{3,60}", re.IGNORECASE
)


def _extract_division_hint(node: Tag, text: str) -> str:
    for selector in _DIVISION_SELECTORS:
        element = node.select_one(selector)
        if element:
            value = clean_text(element.get_text(" ", strip=True))
            if value and len(value) < 150:
                return value
    match = _DIVISION_TEXT_RE.search(text)
    return match.group(0).strip() if match else ""


def _extract_name_from_node(node: Tag) -> str | None:
    for selector in (
        '[itemprop="name"]', '[class*="name" i]',
        "h1", "h2", "h3", "h4", "strong", "b",
    ):
        for child in node.select(selector):
            candidate = clean_name(child.get_text(" ", strip=True))
            if valid_name(candidate):
                return candidate
    for anchor in node.select("a[href]"):
        candidate = clean_name(anchor.get_text(" ", strip=True))
        if valid_name(candidate):
            return candidate
    return None


def collect_names_in_node(node: Tag, limit: int = 6) -> set[str]:
    """
    All distinct person names inside a container. Used to tell a single
    person's card apart from a list container holding several people —
    attaching an email found in a multi-person container to whichever name
    happened to parse first is a misattribution.
    """
    names: set[str] = set()
    for selector in (
        '[itemprop="name"]', '[class*="name" i]',
        "h1", "h2", "h3", "h4", "strong", "b", "a[href]",
    ):
        for child in node.select(selector):
            candidate = clean_name(child.get_text(" ", strip=True))
            if valid_name(candidate):
                names.add(normalize_person_name(candidate))
                if len(names) > limit:
                    return names
    return names


_TITLE_SELECTORS = (
    '[class*="title" i]', '[class*="role" i]', '[class*="position" i]',
    '[class*="rank" i]', '[class*="appointment" i]', '[class*="job" i]',
)
_TITLE_WINDOW = 180


def extract_title_text(node: Tag, full_text: str, name: str | None) -> str:
    """
    Narrow the text the role gate reads to the person's actual title.

    Scanning the whole card wrongly excluded real faculty whose *biography*
    mentions a fellowship or an emeritus colleague — the exclusion patterns
    must only see title-like text.
    """
    for selector in _TITLE_SELECTORS:
        element = node.select_one(selector)
        if element:
            value = clean_text(element.get_text(" ", strip=True))
            if 3 <= len(value) <= 200:
                return value

    if name:
        index = full_text.find(name)
        if index != -1:
            start = index + len(name)
            return full_text[start:start + _TITLE_WINDOW]
    return full_text[:_TITLE_WINDOW]


def extract_roster_entries_from_page(
    page_url: str,
    soup: BeautifulSoup,
) -> tuple[list[RosterEntry], list[Rejection]]:
    """
    Parse one already-fetched, already-specialty-matched page for faculty
    roster candidates. Returns (approved_entries, role_rejections).
    Caller is responsible for confirming the page mentions a specialty term
    before calling this — this function only applies the title gate.
    """
    entries: list[RosterEntry] = []
    rejections: list[Rejection] = []
    seen_on_page: set[str] = set()

    for node in soup.select(_CANDIDATE_NODE_SELECTOR):
        text = clean_text(node.get_text(" ", strip=True))
        if not 10 <= len(text) <= 1800:
            continue

        name = _extract_name_from_node(node)
        if not name:
            continue

        # Gate on title-scoped text, not the whole card, so bio prose can't
        # trigger a false exclusion.
        title_text = extract_title_text(node, text, name)
        reason = excluded_role_reason(title_text)
        allowed_phrase = matched_allowed_title(title_text)

        if reason or not allowed_phrase:
            if reason:
                rejections.append(Rejection(
                    name=name,
                    reason=reason,
                    source_url=page_url,
                    detail=title_text[:200],
                ))
            continue

        normalized = normalize_person_name(name)
        if not normalized or normalized in seen_on_page:
            continue
        seen_on_page.add(normalized)

        entries.append(RosterEntry(
            name=name,
            normalized_name=normalized,
            title=allowed_phrase.title(),
            division=_extract_division_hint(node, text),
            roster_source_url=page_url,
            evidence=text[:500],
        ))

    return entries, rejections


def discover_faculty_roster(
    department_urls: list[str],
    official_url: str,
    terms: list[str],
    max_pages: int,
    delay_seconds: float,
) -> tuple[list[RosterEntry], list[str], list[Rejection], list[str], dict[str, str]]:
    """
    Crawl outward from department_urls, following pagination and
    faculty/specialty-relevant links, building the approved roster.

    Returns (roster_entries, faculty_pages_found, role_rejections, crawl_log,
    page_html_cache). page_html_cache lets profile_discovery re-use already
    fetched pages instead of hitting the network again for the same URL.
    """
    session = new_session()
    official_host = host_of(official_url)
    queue: deque[str] = deque(department_urls)
    visited = VisitedPages()
    roster: dict[str, RosterEntry] = {}
    faculty_pages: list[str] = []
    all_rejections: list[Rejection] = []
    log: list[str] = []
    page_html_cache: dict[str, str] = {}

    while queue and len(visited) < max_pages:
        raw_url = queue.popleft()
        normalized = normalize_url(raw_url)
        if not normalized or normalized in visited:
            continue
        if not related_official_domain(normalized, official_host):
            continue
        visited.mark(normalized)

        html, final_url = fetch_html(session, normalized)
        if not html or not final_url:
            log.append(f"Could not access: {normalized}")
            continue
        if not related_official_domain(final_url, official_host):
            continue

        page_html_cache[final_url] = html
        soup = BeautifulSoup(html, "html.parser")
        title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        page_text = clean_text(soup.get_text(" ", strip=True))
        lowered_page = page_text.lower()
        lowered_url_title = f"{final_url} {title}".lower()

        if any(term in lowered_url_title for term in FACULTY_TERMS):
            faculty_pages.append(final_url)

        # Reject unrelated pages before roster extraction begins.
        if any(term in lowered_page or term in final_url.lower() for term in terms):
            entries, rejections = extract_roster_entries_from_page(final_url, soup)
            for entry in entries:
                existing = roster.get(entry.normalized_name)
                if not existing:
                    roster[entry.normalized_name] = entry
            all_rejections.extend(rejections)

        # Pagination: page-number / "next" links.
        for page_link in find_pagination_links(soup, final_url):
            if page_link not in visited and related_official_domain(page_link, official_host):
                queue.append(page_link)

        # Follow same-domain links that look specialty- or faculty-relevant.
        for anchor in soup.find_all("a", href=True):
            link = normalize_url(urljoin(final_url, anchor.get("href", "")))
            if not link or link in visited:
                continue
            if not related_official_domain(link, official_host):
                continue
            link_text = clean_text(anchor.get_text(" ", strip=True))
            combined = f"{link} {link_text}".lower()
            if any(term in combined for term in terms) or any(term in combined for term in FACULTY_TERMS):
                queue.append(link)

        log.append(f"[{len(visited)}/{max_pages}] {final_url}")
        polite_sleep(delay_seconds)

    return (
        list(roster.values()),
        sorted(set(faculty_pages)),
        all_rejections,
        log,
        page_html_cache,
    )
