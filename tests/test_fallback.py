from core.fallback import build_fallback_contact, is_generic_department_local
from core.specialties import resolve_terms


def test_general_purpose_prefix_is_generic():
    assert is_generic_department_local("info", [])
    assert is_generic_department_local("contact", [])


def test_department_level_mailbox_is_generic():
    # Real case: medicine@iu.edu is a department mailbox, not a person.
    assert is_generic_department_local("medicine", [])
    assert is_generic_department_local("nursing", [])


def test_specialty_named_mailbox_is_generic():
    terms = resolve_terms("Obstetrics and Gynecology", "")
    assert is_generic_department_local("obgyn", terms)


def test_personal_local_part_is_not_generic():
    assert not is_generic_department_local("jsmith", [])
    assert not is_generic_department_local("ntefera", [])


def test_fallback_contact_matches_required_shape():
    contact = build_fallback_contact(
        "medicine@iu.edu",
        "https://medicine.iu.edu/obgyn",
        "Indiana University School of Medicine",
        "Obstetrics and Gynecology",
    )
    row = contact.as_row()
    assert row["Name"] == "Department Contact"
    assert row["Email"] == "medicine@iu.edu"
    assert row["Faculty Title"] == ""
    assert row["Division or Unit"] == ""
    assert row["Profile Source URL"] == ""
    assert row["Extraction Method"] == "Department fallback"
    assert row["Verification Status"] == "No public personal faculty email found"
