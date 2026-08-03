"""
Specialty keyword registry.

CRITICAL DEPARTMENT-FIRST RULE (per project spec): the selected dropdown
department controls the entire workflow. Each entry below is its own
keyword set — nothing is shared or inferred across departments. Custom
keywords entered by the user EXTEND the selected department's terms; they
never replace them (except for the literal "Custom Department" option,
which has no built-in terms of its own).
"""

from __future__ import annotations

import re


SPECIALTIES = [
    "Obstetrics and Gynecology",
    "Pediatrics",
    "Nursing",
    "Physiotherapy",
    "Cardiology",
    "Dentistry",
    "Oncology",
    "Neurology",
    "Psychiatry",
    "Public Health",
    "Pharmacy",
    "Radiology",
    "Orthopedics",
    "Emergency Medicine",
    "Custom Department",
]

SPECIALTY_TERMS: dict[str, list[str]] = {
    "Obstetrics and Gynecology": [
        "obstetrics", "gynecology", "gynaecology", "ob-gyn", "obgyn",
        "ob/gyn", "women's health", "womens health",
        "maternal-fetal medicine", "maternal fetal medicine",
        "reproductive endocrinology", "gynecologic oncology",
        "gynaecologic oncology", "urogynecology", "urogynaecology",
        "family planning",
    ],
    "Pediatrics": [
        "pediatrics", "paediatrics", "child health", "neonatology",
        "adolescent medicine", "pediatric surgery", "paediatric surgery",
    ],
    "Nursing": [
        "nursing", "school of nursing", "college of nursing",
        "nursing science", "nursing faculty", "adult health nursing",
        "community health nursing", "pediatric nursing",
        "paediatric nursing",
    ],
    "Physiotherapy": [
        "physiotherapy", "physical therapy", "rehabilitation",
        "kinesiology", "exercise science",
    ],
    "Cardiology": [
        "cardiology", "cardiovascular medicine", "cardiovascular sciences",
        "heart institute", "cardiac sciences", "cardiovascular health",
    ],
    "Dentistry": [
        "dentistry", "dental medicine", "dental school", "oral health",
        "oral and maxillofacial",
    ],
    "Oncology": [
        "oncology", "medical oncology", "radiation oncology",
        "cancer center", "cancer centre", "cancer institute",
    ],
    "Neurology": [
        "neurology", "clinical neuroscience", "neurosciences",
        "brain sciences", "neurological sciences",
    ],
    "Psychiatry": [
        "psychiatry", "mental health", "behavioral health",
        "behavioural health", "psychological medicine",
    ],
    "Public Health": [
        "public health", "population health", "epidemiology",
        "community health", "global health",
    ],
    "Pharmacy": [
        "pharmacy", "pharmaceutical sciences", "pharmacology",
        "clinical pharmacy", "school of pharmacy",
    ],
    "Radiology": [
        "radiology", "medical imaging", "diagnostic imaging",
        "radiological sciences", "imaging sciences",
    ],
    "Orthopedics": [
        "orthopedics", "orthopaedics", "orthopedic surgery",
        "orthopaedic surgery", "musculoskeletal medicine",
    ],
    "Emergency Medicine": [
        "emergency medicine", "emergency department",
        "acute care", "emergency medical services",
    ],
    "Custom Department": [],
}


def clean_term(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip().lower()


def resolve_terms(specialty: str, custom_keywords: str = "") -> list[str]:
    """
    Return the full, deduplicated keyword set for a run: the department's
    built-in terms plus any user-supplied custom keywords appended (never
    substituted), per the spec's "extend rather than replace" rule.
    """
    terms = list(SPECIALTY_TERMS.get(specialty, []))
    extra = [clean_term(term) for term in (custom_keywords or "").split(",")]
    terms.extend(term for term in extra if term)
    # Preserve first-seen order while deduplicating — order affects nothing
    # functionally but keeps the "keywords used" UI display stable/readable.
    seen = set()
    ordered = []
    for term in terms:
        if term and term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered
