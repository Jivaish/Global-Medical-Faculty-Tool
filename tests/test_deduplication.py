from core.deduplication import deduplicate_contacts
from core.models import Contact


def make_contact(**overrides) -> Contact:
    base = dict(
        name="Jane Smith",
        email="jsmith@med.stanford.edu",
        institution="Stanford University",
        department="Obstetrics and Gynecology",
        faculty_title="Professor",
        division_or_unit="",
        roster_source_url="https://med.stanford.edu/obgyn/faculty",
        profile_source_url="",
        extraction_method="Faculty directory result",
    )
    base.update(overrides)
    return Contact(**base)


def test_exact_email_duplicate_collapsed():
    contacts = [make_contact(), make_contact()]
    result = deduplicate_contacts(contacts)
    assert len(result) == 1


def test_stronger_source_wins_on_email_collision():
    weak = make_contact(extraction_method="Faculty directory result")
    strong = make_contact(extraction_method="Official personal profile", profile_source_url="https://profiles.stanford.edu/jsmith")
    result = deduplicate_contacts([weak, strong])
    assert len(result) == 1
    assert result[0].extraction_method == "Official personal profile"


def test_stronger_source_wins_regardless_of_input_order():
    strong = make_contact(extraction_method="Official personal profile")
    weak = make_contact(extraction_method="Faculty directory result")
    result = deduplicate_contacts([weak, strong])
    assert result[0].extraction_method == "Official personal profile"


def test_same_name_different_email_same_institution_department_collapsed():
    a = make_contact(email="jsmith@med.stanford.edu")
    b = make_contact(email="jane.smith@med.stanford.edu")
    result = deduplicate_contacts([a, b])
    assert len(result) == 1


def test_same_name_different_department_kept_separate():
    a = make_contact(department="Obstetrics and Gynecology")
    b = make_contact(department="Pediatrics", email="jsmith2@med.stanford.edu")
    result = deduplicate_contacts([a, b])
    assert len(result) == 2


def test_different_people_kept_separate():
    a = make_contact(name="Jane Smith", email="jsmith@med.stanford.edu")
    b = make_contact(name="John Doe", email="jdoe@med.stanford.edu")
    result = deduplicate_contacts([a, b])
    assert len(result) == 2


def test_empty_input_returns_empty():
    assert deduplicate_contacts([]) == []
