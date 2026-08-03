"""
Institution / domain verification.

Everything downstream (department discovery, roster discovery, email
validation) must stay on the "official" domain family for the institution
the user entered. This module is the single source of truth for what counts
as official so that rule can't drift between files.
"""

from __future__ import annotations

from urllib.parse import urldefrag, urlparse

import requests


def clean_url(url: str) -> str:
    return (url or "").strip()


def normalize_url(url: str) -> str | None:
    """Strip fragments, validate scheme/host, and drop obvious binary/media links."""
    if not url:
        return None
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path.lower().endswith((
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".zip", ".rar", ".mp3", ".mp4", ".mov", ".avi",
    )):
        return None
    return url.rstrip("/")


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def organization_root(host: str) -> str:
    """
    Lightweight institutional-root matcher, e.g. med.stanford.edu -> stanford.edu.

    This intentionally only looks at the last two labels. It is a heuristic,
    not a public-suffix-list implementation — good enough to relate
    subdomains of the same university without treating unrelated domains
    (e.g. a copy-pasted third-party directory) as official.
    """
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def same_official_domain(url: str, official_host: str) -> bool:
    host = host_of(url)
    return bool(host) and (host == official_host or host.endswith("." + official_host))


def related_official_domain(url: str, official_host: str) -> bool:
    """
    True if url is on the exact official host, a subdomain of it, OR shares
    the same organization root (e.g. profiles.stanford.edu when the official
    host is med.stanford.edu). Adapters may further widen this per
    institution — see adapters/stanford.py.
    """
    host = host_of(url)
    if not host:
        return False
    if same_official_domain(url, official_host):
        return True
    return organization_root(host) == organization_root(official_host)


def fetch_robots_txt(session: requests.Session, official_url: str, headers: dict, timeout: int = 10) -> str | None:
    """Best-effort robots.txt fetch. Returns raw text, or None if unavailable."""
    parsed = urlparse(official_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    try:
        response = session.get(f"{root}/robots.txt", headers=headers, timeout=timeout)
        if response.status_code == 200:
            return response.text
    except requests.RequestException:
        pass
    return None


def parse_disallowed_paths(robots_text: str, user_agent_token: str = "*") -> list[str]:
    """
    Minimal robots.txt parser: returns Disallow paths that apply to the
    matching User-agent block (falls back to '*'). Not a full RFC 9309
    implementation, but enough to respect explicit crawl exclusions on
    official department/faculty paths, which is what the spec asks for
    ("respect robots.txt where practical").
    """
    disallowed: list[str] = []
    current_agents: list[str] = []
    applies = False

    for raw_line in (robots_text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            current_agents = [value.lower()]
            applies = value == "*" or value.lower() == user_agent_token.lower()
        elif key == "disallow" and applies and value:
            disallowed.append(value)

    return disallowed


def is_path_allowed(url: str, disallowed_paths: list[str]) -> bool:
    path = urlparse(url).path or "/"
    return not any(path.startswith(rule) for rule in disallowed_paths)
