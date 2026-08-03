"""
Deduplication.

Per spec: dedupe using (1) normalized email, (2) normalized full name +
institution + department. When the same person shows up from more than one
source, keep the strongest: official personal profile > faculty-directory
card > department page (core.models.SOURCE_STRENGTH encodes this order).
"""

from __future__ import annotations

from core.faculty_validation import normalize_person_name
from core.models import Contact


def _better(a: Contact, b: Contact) -> Contact:
    return a if a.source_strength() <= b.source_strength() else b


def deduplicate_contacts(contacts: list[Contact]) -> list[Contact]:
    by_email: dict[str, Contact] = {}
    order: list[str] = []

    for contact in contacts:
        email_key = contact.dedup_email_key()
        if email_key in by_email:
            by_email[email_key] = _better(by_email[email_key], contact)
        else:
            by_email[email_key] = contact
            order.append(email_key)

    stage_one = [by_email[key] for key in order]

    by_name: dict[str, Contact] = {}
    name_order: list[str] = []

    for contact in stage_one:
        name_key = (
            f"{normalize_person_name(contact.name)}|"
            f"{contact.institution.strip().casefold()}|"
            f"{contact.department.strip().casefold()}"
        )
        if name_key in by_name:
            by_name[name_key] = _better(by_name[name_key], contact)
        else:
            by_name[name_key] = contact
            name_order.append(name_key)

    return [by_name[key] for key in name_order]
