"""
Fixture-based integration tests for the roster -> email path.

These use local HTML rather than the network so the accept path (an approved
faculty member WITH a visible institutional email) and the reject paths are
both pinned down deterministically.
"""

from bs4 import BeautifulSoup

from core.faculty_validation import normalize_person_name
from core.profile_discovery import extract_card_level_contacts
from core.roster_discovery import extract_roster_entries_from_page
from core.models import RejectionReason

ROSTER_HTML = """
<html><body>
<h1>Department of Obstetrics and Gynecology — Faculty</h1>
<ul class="faculty-list">
  <li class="faculty-card">
    <h3 class="name">Jane A. Smith, MD</h3>
    <p class="title">Professor of Obstetrics and Gynecology</p>
    <p class="division">Division of Maternal-Fetal Medicine</p>
    <a href="mailto:jsmith@example-univ.edu">jsmith@example-univ.edu</a>
  </li>
  <li class="faculty-card">
    <h3 class="name">Robert Chen</h3>
    <p class="title">Associate Professor</p>
    <a href="mailto:rchen@example-univ.edu">rchen@example-univ.edu</a>
  </li>
  <li class="faculty-card">
    <h3 class="name">Emily Stafford</h3>
    <p class="title">Clinical Assistant Professor</p>
    <a href="mailto:estafford@example-univ.edu">estafford@example-univ.edu</a>
  </li>
  <li class="faculty-card">
    <h3 class="name">Paul Nguyen</h3>
    <p class="title">Professor Emeritus of Gynecology</p>
    <a href="mailto:pnguyen@example-univ.edu">pnguyen@example-univ.edu</a>
  </li>
  <li class="faculty-card">
    <h3 class="name">Dana Ruiz</h3>
    <p class="title">Clinical Fellow, Maternal-Fetal Medicine</p>
    <a href="mailto:druiz@example-univ.edu">druiz@example-univ.edu</a>
  </li>
  <li class="faculty-card">
    <h3 class="name">Karen Diaz</h3>
    <p class="title">Program Coordinator</p>
    <a href="mailto:kdiaz@example-univ.edu">kdiaz@example-univ.edu</a>
  </li>
</ul>
</body></html>
"""

PAGE_URL = "https://example-univ.edu/obgyn/faculty"
HOST = "example-univ.edu"


def build_roster():
    soup = BeautifulSoup(ROSTER_HTML, "html.parser")
    return extract_roster_entries_from_page(PAGE_URL, soup)


def test_approved_roster_contains_only_current_faculty():
    entries, _ = build_roster()
    names = {e.name for e in entries}
    assert "Jane A. Smith" in names
    assert "Robert Chen" in names
    assert "Emily Stafford" in names
    assert "Paul Nguyen" not in names
    assert "Dana Ruiz" not in names
    assert "Karen Diaz" not in names


def test_roster_captures_title_and_division():
    entries, _ = build_roster()
    jane = next(e for e in entries if e.name == "Jane A. Smith")
    assert "Professor" in jane.title
    assert "Maternal-Fetal Medicine" in jane.division
    assert jane.roster_source_url == PAGE_URL


def test_rejections_carry_specific_reasons():
    _, rejections = build_roster()
    reasons = {r.name: r.reason for r in rejections}
    assert reasons.get("Paul Nguyen") == RejectionReason.EMERITUS
    assert reasons.get("Dana Ruiz") == RejectionReason.FELLOW
    assert reasons.get("Karen Diaz") == RejectionReason.STAFF_ROLE


def test_emails_extracted_only_for_approved_faculty():
    entries, _ = build_roster()
    contacts, _ = extract_card_level_contacts(
        roster_entries=entries,
        page_html_cache={PAGE_URL: ROSTER_HTML},
        official_host=HOST,
        institution="Example University",
        department="Obstetrics and Gynecology",
        already_covered=set(),
    )
    emails = {c.email for c in contacts}
    assert "jsmith@example-univ.edu" in emails
    assert "rchen@example-univ.edu" in emails
    assert "estafford@example-univ.edu" in emails
    # Excluded roles never reach email extraction at all.
    assert "pnguyen@example-univ.edu" not in emails
    assert "druiz@example-univ.edu" not in emails
    assert "kdiaz@example-univ.edu" not in emails


def test_extracted_contacts_carry_full_csv_fields():
    entries, _ = build_roster()
    contacts, _ = extract_card_level_contacts(
        roster_entries=entries,
        page_html_cache={PAGE_URL: ROSTER_HTML},
        official_host=HOST,
        institution="Example University",
        department="Obstetrics and Gynecology",
        already_covered=set(),
    )
    jane = next(c for c in contacts if c.email == "jsmith@example-univ.edu")
    assert jane.institution == "Example University"
    assert jane.department == "Obstetrics and Gynecology"
    assert "Professor" in jane.faculty_title
    assert jane.roster_source_url == PAGE_URL
    assert jane.extraction_method == "Faculty directory result"


ADMIN_PROFILE_HTML = """
<html><body>
  <h1>Margaret T. Fuller</h1>
  <p class="title">Professor of Obstetrics and Gynecology</p>
  <section>
    <h3>Contact</h3><h4>Alternate Contact</h4>
    <p>Ngan Tefera</p><p>Administrative Assistant</p>
    <a href="mailto:ntefera@example-univ.edu">ntefera@example-univ.edu</a>
  </section>
</body></html>
"""


def test_administrative_assistant_email_not_attributed_to_faculty():
    # Mirrors the real Stanford profile layout that caused an assistant's
    # address to be returned as the faculty member's email.
    from core.profile_discovery import _parse_profile_page

    contacts, rejections = _parse_profile_page(
        url="https://example-univ.edu/profiles/margaret-fuller",
        html=ADMIN_PROFILE_HTML,
        official_host=HOST,
        roster_names={normalize_person_name("Margaret T. Fuller")},
        institution="Example University",
        department="Obstetrics and Gynecology",
    )
    assert contacts == []
    assert any(r.reason == RejectionReason.ADMIN_EMAIL for r in rejections)


MULTI_PERSON_LIST_HTML = """
<html><body>
<div class="faculty-list">
  <h3>Cooper Aakhus</h3><p>Clinical Instructor</p>
  <h3>Alice Bai</h3><p>Professor</p>
  <a href="mailto:abai@example-univ.edu">abai@example-univ.edu</a>
</div>
</body></html>
"""


def test_multi_person_container_does_not_misattribute_email():
    from core.models import RosterEntry

    entry = RosterEntry(
        name="Cooper Aakhus",
        normalized_name=normalize_person_name("Cooper Aakhus"),
        title="Clinical Instructor",
        division="",
        roster_source_url="https://example-univ.edu/list",
    )
    contacts, _ = extract_card_level_contacts(
        roster_entries=[entry],
        page_html_cache={"https://example-univ.edu/list": MULTI_PERSON_LIST_HTML},
        official_host=HOST,
        institution="Example University",
        department="Obstetrics and Gynecology",
        already_covered=set(),
    )
    assert all(c.email != "abai@example-univ.edu" for c in contacts)
