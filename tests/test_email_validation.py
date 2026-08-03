from core.email_validation import (
    classify_email,
    decode_visible_emails,
    domain_belongs_to_institution,
    is_admin_context,
    valid_email,
)
from core.models import RejectionReason


def test_valid_institutional_email_accepted():
    assert valid_email("jsmith@med.stanford.edu", "med.stanford.edu")


def test_subdomain_of_official_root_accepted():
    # official host is a subdomain; email is on the shared org root.
    assert valid_email("jsmith@stanford.edu", "med.stanford.edu")


def test_related_stanford_sibling_subdomain_accepted():
    assert valid_email("jsmith@profiles.stanford.edu", "med.stanford.edu")


def test_personal_domain_rejected():
    ok, reason = classify_email("jsmith@gmail.com", "med.stanford.edu")
    assert not ok
    assert reason == RejectionReason.PERSONAL_DOMAIN


def test_generic_prefix_rejected():
    ok, reason = classify_email("info@med.stanford.edu", "med.stanford.edu")
    assert not ok
    assert reason == RejectionReason.GENERIC_EMAIL


def test_outside_official_domain_rejected():
    ok, reason = classify_email("jsmith@unrelated-university.edu", "med.stanford.edu")
    assert not ok
    assert reason == RejectionReason.OUTSIDE_DOMAIN


def test_malformed_email_rejected():
    ok, reason = classify_email("not-an-email", "med.stanford.edu")
    assert not ok


def test_decode_bracket_obfuscation():
    emails = decode_visible_emails("Contact: jsmith [at] med.stanford.edu")
    assert "jsmith@med.stanford.edu" in emails


def test_decode_paren_obfuscation_with_dot():
    emails = decode_visible_emails("jsmith (at) med (dot) stanford (dot) edu")
    assert "jsmith@med.stanford.edu" in emails


def test_decode_plain_email_untouched():
    emails = decode_visible_emails("Reach me at jsmith@med.stanford.edu directly.")
    assert emails == {"jsmith@med.stanford.edu"}


def test_admin_context_detected():
    assert is_admin_context("Administrative Assistant — Executive Assistant to the Chair")


def test_contact_academic_carveout_not_admin():
    assert not is_admin_context("For faculty inquiries, contact academic affairs.")


def test_admin_assistant_email_context_detected():
    # Regression: this exact Stanford profile layout caused an assistant's
    # address to be attributed to the faculty member.
    context = (
        "Contact Alternate Contact Ngan Tefera Administrative Assistant "
        "ntefera@stanford.edu 650-498-7301 (office)"
    )
    assert is_admin_context(context)


def test_extract_emails_with_context_flags_admin_email():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context
    from core.faculty_validation import clean_text

    html = """
    <div>
      <h1>Margaret T. Fuller</h1>
      <section><h3>Contact</h3><h4>Alternate Contact</h4>
        <p>Ngan Tefera</p><p>Administrative Assistant</p>
        <a href="mailto:ntefera@stanford.edu">ntefera@stanford.edu</a>
      </section>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert "ntefera@stanford.edu" in contexts
    assert any(is_admin_context(e["context"]) for e in contexts["ntefera@stanford.edu"])


def test_extract_emails_with_context_keeps_clean_personal_email():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context
    from core.faculty_validation import clean_text

    html = """
    <div><h1>Jane Smith</h1><p>Professor of Obstetrics and Gynecology</p>
    <p>Email: <a href="mailto:jsmith@stanford.edu">jsmith@stanford.edu</a></p></div>
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert "jsmith@stanford.edu" in contexts
    assert not any(is_admin_context(e["context"]) for e in contexts["jsmith@stanford.edu"])


def test_email_in_publication_prose_is_not_a_displayed_contact():
    # Regression: a lab/tool address inside a publication abstract was
    # attributed to the profile owner (real case: Nima Aghaeepour ->
    # gatefinder.gnolan@stanford.edu).
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context, is_displayed_contact
    from core.faculty_validation import clean_text

    html = """
    <div><h1>Nima Aghaeepour</h1>
    <p>The GateFinder algorithm is implemented as a free and open-source
    package for BioConductor: https://nalab.stanford.edu/gatefinder.gnolan@stanford.edu
    or naghaeep@stanford.edu.Supplementary data are available at Bioinformatics online.</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert "gatefinder.gnolan@stanford.edu" in contexts
    assert not is_displayed_contact(contexts["gatefinder.gnolan@stanford.edu"])


def test_run_on_sentence_trimmed_from_address():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context
    from core.faculty_validation import clean_text

    html = "<p>see naghaeep@stanford.edu.Supplementary data are available.</p>"
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert "naghaeep@stanford.edu" in contexts


def test_mailto_link_counts_as_displayed_contact():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context, is_displayed_contact
    from core.faculty_validation import clean_text

    html = '<p><a href="mailto:jsmith@stanford.edu">Write to Jane</a></p>'
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert is_displayed_contact(contexts["jsmith@stanford.edu"])


def test_labeled_plaintext_email_counts_as_displayed_contact():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context, is_displayed_contact
    from core.faculty_validation import clean_text

    html = "<p>Email: jsmith@stanford.edu</p>"
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    contexts = extract_emails_with_context(soup, page_text)
    assert is_displayed_contact(contexts["jsmith@stanford.edu"])


def test_mailto_share_widget_without_recipient_ignored():
    from bs4 import BeautifulSoup
    from core.email_validation import extract_emails_with_context

    html = '<a href="mailto:?subject=Profile&body=Look at this">Share</a>'
    soup = BeautifulSoup(html, "html.parser")
    contexts = extract_emails_with_context(soup, "")
    assert contexts == {}


def test_domain_belongs_to_institution_same_root():
    assert domain_belongs_to_institution("cap.stanford.edu", "med.stanford.edu")


def test_domain_belongs_to_institution_unrelated_rejected():
    assert not domain_belongs_to_institution("gmail.com", "med.stanford.edu")
