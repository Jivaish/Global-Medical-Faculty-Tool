from core.faculty_validation import (
    excluded_role_reason,
    is_allowed_faculty_title,
    matched_allowed_title,
    normalize_person_name,
    roster_name_match,
    valid_name,
)
from core.models import RejectionReason


def test_professor_stafford_is_not_rejected_as_staff():
    # Regression test: the previous version used substring matching against
    # "staff", which rejected any name containing that substring.
    assert valid_name("Dr. Jane Stafford")


def test_administrative_assistant_excluded_as_staff_role():
    assert excluded_role_reason("Jane Doe, Administrative Assistant") == RejectionReason.STAFF_ROLE


def test_program_coordinator_excluded_as_staff_role():
    assert excluded_role_reason("Program Coordinator, Department of Pediatrics") == RejectionReason.STAFF_ROLE


def test_fellow_of_acog_credential_not_excluded():
    # Regression test: "Fellow of the American College of Obstetricians and
    # Gynecologists" is a professional-society credential, not a job title,
    # and must not exclude an otherwise-valid professor.
    text = (
        "Jane Smith, MD. Professor of Obstetrics and Gynecology. "
        "Fellow of the American College of Obstetricians and Gynecologists."
    )
    assert excluded_role_reason(text) is None
    assert is_allowed_faculty_title(text)


def test_clinical_fellow_trainee_role_is_excluded():
    text = "John Doe, Clinical Fellow, Maternal-Fetal Medicine"
    assert excluded_role_reason(text) == RejectionReason.FELLOW


def test_postdoctoral_fellow_excluded():
    text = "Postdoctoral Fellow in Reproductive Biology"
    assert excluded_role_reason(text) == RejectionReason.FELLOW


def test_assistant_professor_allowed():
    assert matched_allowed_title("Jane Smith, Assistant Professor of Pediatrics") is not None


def test_adjunct_professor_excluded_even_though_professor_matches():
    text = "Adjunct Clinical Professor of Nursing"
    assert excluded_role_reason(text) == RejectionReason.ADJUNCT
    assert not is_allowed_faculty_title(text)


def test_emeritus_excluded():
    assert excluded_role_reason("Professor Emeritus of Cardiology") == RejectionReason.EMERITUS


def test_resident_excluded():
    assert excluded_role_reason("Resident, Department of Obstetrics") == RejectionReason.RESIDENT


def test_student_excluded():
    assert excluded_role_reason("PhD Student, Nursing Science") == RejectionReason.STUDENT


def test_nurse_practitioner_excluded_as_staff_role():
    assert excluded_role_reason("Nurse Practitioner, Women's Health") == RejectionReason.STAFF_ROLE


def test_no_title_at_all_is_not_allowed():
    assert not is_allowed_faculty_title("Jane Smith, Department Administrator")


def test_page_heading_is_not_a_valid_name():
    # Regression: NAME_RE was compiled with re.IGNORECASE, which disabled its
    # own capitalization requirement, so headings validated as person names.
    assert not valid_name("Current Research and Scholarly Interests")
    assert not valid_name("Graduate School of Business")
    assert not valid_name("Office of External Relations")
    assert not valid_name("Vice Provost for Student Affairs")


def test_real_names_still_valid():
    assert valid_name("Margaret T. Fuller")
    assert valid_name("Virginia D. Winn, MD, PhD")
    assert valid_name("Bo Yu, MD")
    assert valid_name("Yair Blumenfeld")


def test_lowercase_particles_allowed_in_names():
    assert valid_name("Ludwig van Beethoven")
    assert valid_name("Maria de la Cruz")


def test_credentials_stripped_from_stored_name():
    from core.faculty_validation import clean_name
    assert clean_name("Virginia D. Winn, MD, PhD") == "Virginia D. Winn"
    assert clean_name("Bo Yu, MD") == "Bo Yu"


def test_single_token_is_not_a_name():
    assert not valid_name("Smith")


def test_roster_name_match_exact():
    roster = {normalize_person_name("Jane A. Smith")}
    assert roster_name_match("Jane A. Smith", roster)


def test_roster_name_match_first_last_fallback():
    roster = {normalize_person_name("Jane Smith")}
    assert roster_name_match("Dr. Jane A. Smith, MD", roster)


def test_roster_name_match_rejects_unrelated_name():
    roster = {normalize_person_name("Jane Smith")}
    assert not roster_name_match("John Doe", roster)
