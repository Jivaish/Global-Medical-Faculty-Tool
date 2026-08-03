"""
Stanford-specific adapter.

Stanford splits faculty information across med.stanford.edu (departments),
profiles.stanford.edu / cap.stanford.edu (CAP directory + individual
profiles). This adapter recognizes CAP "browse" links discovered by generic
department discovery and turns them into faculty-filtered, 100-results-per-
page directory URLs — but it never trusts the capFaculty filter alone;
roster_discovery still applies the normal strict title gate to whatever
those pages return, exactly like every other institution.

Isolated on purpose: only Stanford-family hosts trigger this adapter, so it
cannot affect crawling for any other university.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from core.domains import normalize_url, organization_root

STANFORD_ROOT = "stanford.edu"


class StanfordAdapter:
    name = "Stanford"

    def applies_to(self, official_host: str) -> bool:
        return organization_root(official_host) == STANFORD_ROOT

    def extra_candidate_urls(self, department_candidate_urls: list[str]) -> list[str]:
        generated: list[str] = []
        seen: set[str] = set()

        for raw_url in department_candidate_urls:
            normalized = normalize_url(raw_url)
            if not normalized:
                continue

            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            query = parse_qs(parsed.query)
            org_values = query.get("org", [])

            is_cap_browse = (
                organization_root(host) == STANFORD_ROOT
                and (
                    "/browse/" in parsed.path
                    or parsed.path.endswith("/profiles/browse")
                    or parsed.path.endswith("/profiles/browse.html")
                )
                and org_values
            )
            if not is_cap_browse:
                continue

            for org_value in org_values:
                params = {
                    "affiliations": "capFaculty",
                    "org": org_value,
                    "p": "1",
                    "ps": "100",
                }
                directory_url = urlunparse((
                    "https",
                    "profiles.stanford.edu",
                    "/browse/school-of-medicine",
                    "",
                    urlencode(params),
                    "",
                ))
                if directory_url not in seen:
                    seen.add(directory_url)
                    generated.append(directory_url)

        return generated


DEFAULT_ADAPTERS = [StanfordAdapter()]
