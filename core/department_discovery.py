"""
Department discovery.

Finds candidate department pages via homepage links, XML sitemaps, and
common URL-path guessing, then rejects anything that doesn't mention at
least one selected-specialty term — per spec, unrelated department pages
must be rejected BEFORE faculty extraction begins, not merely down-ranked.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from core.crawler import discover_sitemaps, extract_sitemap_urls, fetch, fetch_html, new_session
from core.domains import host_of, normalize_url, related_official_domain
from core.faculty_validation import clean_text
from core.models import DepartmentCandidate

FACULTY_TERMS = [
    "faculty", "people", "staff", "directory", "our team",
    "professor", "associate professor", "assistant professor",
    "instructor", "lecturer", "chair", "chief", "director",
    "profile", "provider", "physician",
]


def url_relevance_score(url: str, title: str, terms: list[str]) -> int:
    combined = f"{url} {title}".lower()
    score = 0
    score += 30 * sum(term in combined for term in terms)
    score += 12 * sum(term in combined for term in FACULTY_TERMS)
    if any(word in combined for word in ("department", "division", "school", "college")):
        score += 15
    if any(word in combined for word in ("faculty", "people", "directory", "profile")):
        score += 20
    return score


def common_department_paths(official_url: str, terms: list[str]) -> list[str]:
    parsed = urlparse(official_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    slugs = set()

    for term in terms:
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
        compact = re.sub(r"[^a-z0-9]+", "", term.lower())
        if slug:
            slugs.add(slug)
        if compact:
            slugs.add(compact)

    paths = set()
    prefixes = ("", "departments", "department", "specialties", "clinical", "academics", "education")
    for slug in slugs:
        for prefix in prefixes:
            path = f"/{prefix}/{slug}" if prefix else f"/{slug}"
            paths.add(root + path)

    return sorted(paths)


def discover_department_pages(
    official_url: str,
    terms: list[str],
    max_sitemap_urls: int = 3000,
) -> tuple[list[DepartmentCandidate], list[str]]:
    session = new_session()
    official_host = host_of(official_url)
    candidates: dict[str, DepartmentCandidate] = {}
    log: list[str] = []

    def add_candidate(url: str, title: str, source: str, page_text: str = "") -> None:
        normalized = normalize_url(url)
        if not normalized or not related_official_domain(normalized, official_host):
            return

        evidence = f"{normalized} {title} {page_text[:2500]}".lower()
        matched_terms = [term for term in terms if term in evidence]

        # Reject unrelated department pages before extraction: no matched
        # specialty term means this URL never enters the candidate pool.
        if not matched_terms:
            return

        score = url_relevance_score(normalized, f"{title} {page_text[:2500]}", terms)
        if score <= 0:
            return

        existing = candidates.get(normalized)
        record = DepartmentCandidate(
            url=normalized,
            title=clean_text(title),
            matched_terms=matched_terms,
            discovery_source=source,
            score=score,
        )
        if not existing or score > existing.score:
            candidates[normalized] = record

    # 1. Homepage links
    html, final_url = fetch_html(session, official_url)
    if html and final_url:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            link = normalize_url(urljoin(final_url, anchor.get("href", "")))
            text = clean_text(anchor.get_text(" ", strip=True))
            if link:
                add_candidate(link, text, "homepage_link", text)
        log.append("Homepage links checked.")
    else:
        log.append("Homepage could not be read.")

    # 2. Sitemaps (robots.txt + default paths)
    sitemap_count = 0
    for sitemap_url in discover_sitemaps(session, official_url):
        response, final_sitemap = fetch(session, sitemap_url)
        if not response or not final_sitemap:
            continue
        content_type = response.headers.get("Content-Type", "").lower()
        if "xml" not in content_type and "<urlset" not in response.text and "<sitemapindex" not in response.text:
            continue

        urls = extract_sitemap_urls(response.text)
        for found_url in urls[:max_sitemap_urls]:
            sitemap_count += 1
            if found_url.lower().endswith(".xml"):
                nested_response, _ = fetch(session, found_url)
                if nested_response:
                    for nested_url in extract_sitemap_urls(nested_response.text)[:max_sitemap_urls]:
                        add_candidate(nested_url, "", "nested_sitemap", "")
            else:
                add_candidate(found_url, "", "sitemap", "")

    log.append(f"Sitemap URLs checked: {sitemap_count}")

    # 3. Common department paths
    for candidate_url in common_department_paths(official_url, terms):
        response, final_candidate = fetch(session, candidate_url)
        if not response or not final_candidate:
            continue
        if not related_official_domain(final_candidate, official_host):
            continue
        if "html" not in response.headers.get("Content-Type", "").lower():
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        text = clean_text(soup.get_text(" ", strip=True)).lower()
        if any(term in text for term in terms):
            add_candidate(final_candidate, title, "common_path", text)

    log.append("Common department paths checked.")

    ordered = sorted(candidates.values(), key=lambda item: (-item.score, item.url))
    return ordered, log
