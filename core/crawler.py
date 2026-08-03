"""
Shared HTTP/session layer.

Every other module fetches pages through here so timeout, user-agent,
response-size limits and in-run caching behave identically everywhere, and
so there is exactly one place to tighten crawl safety later.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.domains import fetch_robots_txt, normalize_url

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GlobalMedicalFacultyFinder/0.5; "
        "+https://streamlit.app)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT = 18
# Refuse to download bodies bigger than this — protects against being handed
# a large PDF/binary mislabeled as text, per "avoid downloading large files".
MAX_RESPONSE_BYTES = 6 * 1024 * 1024


def new_session() -> requests.Session:
    return requests.Session()


def fetch(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT):
    """GET a URL. Returns (response, normalized_final_url) or (None, None)."""
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            response.close()
            return None, None

        # Read with a hard cap even when Content-Length is absent/misleading.
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                response.close()
                return None, None
            chunks.append(chunk)
        response._content = b"".join(chunks)

        final_url = normalize_url(response.url)
        return response, final_url
    except requests.RequestException:
        return None, None


def fetch_html(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT):
    """Returns (html_text, final_url) or (None, final_url_or_None)."""
    response, final_url = fetch(session, url, timeout=timeout)
    if not response or not final_url:
        return None, None
    if "html" not in response.headers.get("Content-Type", "").lower():
        return None, final_url
    return response.text, final_url


def extract_sitemap_urls(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    urls = []
    for element in root.iter():
        if element.tag.lower().endswith("loc") and element.text:
            value = normalize_url(element.text.strip())
            if value:
                urls.append(value)
    return urls


def discover_sitemaps(session: requests.Session, official_url: str) -> list[str]:
    parsed = urlparse(official_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_urls = {f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"}

    robots_text = fetch_robots_txt(session, official_url, HEADERS)
    if robots_text:
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                value = normalize_url(line.split(":", 1)[1].strip())
                if value:
                    sitemap_urls.add(value)

    return sorted(sitemap_urls)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

_NEXT_LINK_WORDS = {"next", "next page", "»", "more results", "load more", ">"}


def find_pagination_links(soup: BeautifulSoup, base_url: str, max_links: int = 25) -> list[str]:
    """
    Detect both rel="next" / "next"-labelled links and numbered page links
    (?page=2, ?p=3, &offset=100 style) so roster crawling doesn't stop at
    page 1. Generic — institution-specific pagination (e.g. Stanford's
    p=/ps= params) is handled by the relevant adapter instead.
    """
    found: dict[str, None] = {}

    # rel="next"
    for link in soup.find_all(["a", "link"], rel=True):
        rels = [r.lower() for r in (link.get("rel") or [])]
        if "next" in rels:
            target = normalize_url(urljoin(base_url, link.get("href", "")))
            if target:
                found[target] = None

    # anchor text / aria-label pagination
    for anchor in soup.find_all("a", href=True):
        text = (anchor.get_text(" ", strip=True) or "").strip().lower()
        aria = (anchor.get("aria-label") or "").strip().lower()
        is_numbered = text.isdigit()
        is_next_word = text in _NEXT_LINK_WORDS or aria in _NEXT_LINK_WORDS or "next" in aria
        if is_numbered or is_next_word:
            target = normalize_url(urljoin(base_url, anchor.get("href", "")))
            if target and target != normalize_url(base_url):
                found[target] = None

    return list(found.keys())[:max_links]


class VisitedPages:
    """Small helper so every crawl stage shares one "don't fetch twice" set."""

    def __init__(self) -> None:
        self._visited: set[str] = set()

    def mark(self, url: str) -> bool:
        """Returns True if this is a new URL (and marks it seen)."""
        normalized = normalize_url(url) or url
        if normalized in self._visited:
            return False
        self._visited.add(normalized)
        return True

    def __contains__(self, url: str) -> bool:
        return (normalize_url(url) or url) in self._visited

    def __len__(self) -> int:
        return len(self._visited)


def polite_sleep(delay_seconds: float) -> None:
    if delay_seconds > 0:
        time.sleep(delay_seconds)
