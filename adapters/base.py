"""
Institution-adapter interface.

An adapter may inject extra, institution-specific candidate URLs into the
department-discovery result (e.g. a faculty-filtered directory URL that a
generic crawler would never construct on its own). Adapters must be
additive and isolated: `applies_to` gates the whole adapter to its own
institution's domain family, so a bug or quirk in one adapter can never
reach another university's crawl.
"""

from __future__ import annotations

from typing import Protocol


class InstitutionAdapter(Protocol):
    name: str

    def applies_to(self, official_host: str) -> bool:
        """True if this adapter should run for the given official host."""
        ...

    def extra_candidate_urls(self, department_candidate_urls: list[str]) -> list[str]:
        """
        Given the URLs generic department discovery already found, return
        additional institution-specific URLs to add to the crawl (e.g. a
        faculty-filtered, high-page-size directory URL). Must not remove or
        modify the input list.
        """
        ...


def run_adapters(
    adapters: list[InstitutionAdapter],
    official_host: str,
    department_candidate_urls: list[str],
) -> list[str]:
    """Collects extra URLs from every adapter that applies to this host."""
    extra: list[str] = []
    seen = set(department_candidate_urls)
    for adapter in adapters:
        if not adapter.applies_to(official_host):
            continue
        for url in adapter.extra_candidate_urls(department_candidate_urls):
            if url not in seen:
                seen.add(url)
                extra.append(url)
    return extra
