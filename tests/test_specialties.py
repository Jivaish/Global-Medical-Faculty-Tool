from core.specialties import SPECIALTIES, SPECIALTY_TERMS, resolve_terms


def test_every_dropdown_specialty_has_a_terms_entry():
    for specialty in SPECIALTIES:
        assert specialty in SPECIALTY_TERMS


def test_obgyn_matches_spec_examples():
    terms = SPECIALTY_TERMS["Obstetrics and Gynecology"]
    for expected in [
        "obstetrics", "gynecology", "gynaecology", "ob-gyn", "obgyn",
        "women's health", "maternal-fetal medicine",
        "reproductive endocrinology", "gynecologic oncology",
        "urogynecology", "family planning",
    ]:
        assert expected in terms


def test_pediatrics_matches_spec_examples():
    terms = SPECIALTY_TERMS["Pediatrics"]
    for expected in [
        "pediatrics", "paediatrics", "child health", "neonatology",
        "adolescent medicine", "pediatric surgery",
    ]:
        assert expected in terms


def test_nursing_matches_spec_examples():
    terms = SPECIALTY_TERMS["Nursing"]
    for expected in [
        "school of nursing", "college of nursing", "nursing science",
        "nursing faculty", "adult health nursing",
        "community health nursing", "pediatric nursing",
    ]:
        assert expected in terms


def test_custom_department_has_no_builtin_terms():
    assert SPECIALTY_TERMS["Custom Department"] == []


def test_custom_keywords_extend_not_replace_builtin_terms():
    terms = resolve_terms("Pediatrics", "Kidney Health, Nephrology")
    assert "pediatrics" in terms
    assert "neonatology" in terms
    assert "kidney health" in terms
    assert "nephrology" in terms


def test_custom_keywords_alone_populate_custom_department():
    terms = resolve_terms("Custom Department", "Sports Medicine")
    assert terms == ["sports medicine"]


def test_resolve_terms_deduplicates():
    terms = resolve_terms("Nursing", "Nursing, nursing faculty")
    assert terms.count("nursing") == 1
    assert terms.count("nursing faculty") == 1


def test_resolve_terms_empty_custom_department_is_empty():
    assert resolve_terms("Custom Department", "") == []
