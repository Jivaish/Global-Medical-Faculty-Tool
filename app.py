"""
Global Medical Faculty Contact Finder — Streamlit interface.

This file only wires the pipeline together and renders it. All discovery,
validation, dedup and fallback logic lives in core/ and adapters/ so it can
be unit-tested without Streamlit. The exact validation sequence is:

  domain verification -> specialty keywords -> department discovery
  -> (adapter URL injection) -> faculty-roster discovery (paginated,
  title-gated, roster built BEFORE any email is touched) -> profile
  discovery & parsing (roster-driven only) -> card-level email fallback for
  roster entries without a separate profile -> deduplication
  -> generic department-contact fallback (only if zero personal emails)
  -> CSV export.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from adapters.base import run_adapters
from adapters.stanford import DEFAULT_ADAPTERS
from core.deduplication import deduplicate_contacts
from core.department_discovery import discover_department_pages
from core.domains import host_of, normalize_url
from core.fallback import build_fallback_contact, find_generic_department_email
from core.faculty_validation import normalize_person_name
from core.models import CSV_COLUMNS, Contact, RunSummary
from core.profile_discovery import crawl_individual_profiles, discover_profile_links, extract_card_level_contacts
from core.roster_discovery import discover_faculty_roster
from core.specialties import SPECIALTIES, resolve_terms

st.set_page_config(
    page_title="Global Medical Faculty Contact Finder",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Styling — premium, minimal: quiet neutrals, one accent, generous spacing.
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* The Streamlit theme is pinned to light in .streamlit/config.toml, so
       this palette is fixed to match it. A prefers-color-scheme override
       here would desynchronise from Streamlit's own widget colors and put
       white text on a white background. */
    :root {
        --ink:        #0A0A0B;
        --ink-soft:   #52525B;
        --ink-faint:  #8E8E99;
        --line:       #E8E8EC;
        --line-soft:  #F1F1F4;
        --surface:    #FFFFFF;
        --surface-2:  #FAFAFA;
        --accent:     #4F46E5;
        --accent-bg:  #F0F0FE;
        --radius:     12px;
    }

    html, body, [class*="css"], button, input, textarea, select {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-feature-settings: 'cv02','cv03','cv04','ss01';
    }

    /* The header hosts the sidebar expand control, so keep it and hide only
       the Deploy button and overflow menu. */
    footer { visibility: hidden; height: 0; }
    header[data-testid="stHeader"] { background: transparent; box-shadow: none; }
    div[data-testid="stAppDeployButton"], span[data-testid="stMainMenu"] { display: none; }

    .block-container {
        padding-top: 3.2rem; padding-bottom: 4rem; max-width: 1120px;
    }

    /* ---------------- Hero ---------------- */
    .gmfcf-hero { margin-bottom: 2.75rem; }
    .gmfcf-kicker {
        display: inline-flex; align-items: center; gap: 0.4rem;
        font-size: 0.68rem; font-weight: 600; letter-spacing: 0.09em;
        text-transform: uppercase; color: var(--accent);
        background: var(--accent-bg); padding: 0.3rem 0.7rem;
        border-radius: 999px; margin-bottom: 1.15rem;
    }
    .gmfcf-hero h1 {
        font-size: clamp(1.85rem, 3.4vw, 2.5rem); font-weight: 700;
        letter-spacing: -0.035em; color: var(--ink);
        margin: 0 0 0.6rem 0; line-height: 1.1;
    }
    .gmfcf-hero p {
        font-size: 1.02rem; color: var(--ink-soft); max-width: 34rem;
        margin: 0; line-height: 1.6; letter-spacing: -0.005em;
    }

    /* ---------------- Labels & inputs ---------------- */
    .gmfcf-label {
        font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
        text-transform: uppercase; color: var(--ink-faint);
        margin: 0 0 0.75rem 0;
    }
    div[data-testid="stTextInput"] label p,
    div[data-testid="stTextArea"] label p,
    div[data-testid="stSelectbox"] label p {
        font-size: 0.82rem; font-weight: 500; color: var(--ink-soft);
    }
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        border-radius: 10px !important;
        border: 1px solid var(--line) !important;
        background: var(--surface-2) !important;
        color: var(--ink) !important;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    div[data-testid="stTextInput"] input::placeholder,
    div[data-testid="stTextArea"] textarea::placeholder {
        color: var(--ink-faint) !important;
    }
    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent) !important;
    }

    /* ---------------- Buttons ---------------- */
    .stButton > button, .stDownloadButton > button {
        border-radius: 10px; font-weight: 550; font-size: 0.9rem;
        padding: 0.62rem 1.15rem; border: 1px solid var(--line);
        transition: transform .08s ease, box-shadow .15s ease, background .15s ease;
    }
    .stButton > button:active, .stDownloadButton > button:active { transform: translateY(1px); }
    .stButton > button[kind="primary"] {
        border-color: transparent;
        box-shadow: 0 1px 2px rgba(10,10,11,.08), 0 4px 12px -4px color-mix(in srgb, var(--accent) 45%, transparent);
    }

    /* ---------------- Stat grid ---------------- */
    .gmfcf-stats {
        display: grid; gap: 0.6rem; margin: 0.4rem 0 2rem 0;
        grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
    }
    .gmfcf-stat {
        border: 1px solid var(--line); border-radius: var(--radius);
        background: var(--surface-2); padding: 0.9rem 1rem;
    }
    .gmfcf-stat .v {
        font-size: 1.55rem; font-weight: 650; letter-spacing: -0.03em;
        color: var(--ink); line-height: 1.1;
    }
    .gmfcf-stat .k {
        font-size: 0.72rem; font-weight: 500; color: var(--ink-faint);
        margin-top: 0.3rem; letter-spacing: 0.01em;
    }
    .gmfcf-stat.accent .v { color: var(--accent); }

    /* ---------------- Tabs ---------------- */
    button[data-baseweb="tab"] {
        font-size: 0.88rem !important; font-weight: 500 !important;
        color: var(--ink-faint) !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: var(--ink) !important; font-weight: 600 !important;
    }
    div[data-baseweb="tab-border"] { background: var(--line-soft) !important; }

    /* ---------------- Containers ---------------- */
    div[data-testid="stExpander"] details {
        border: 1px solid var(--line); border-radius: var(--radius);
        background: var(--surface);
    }
    div[data-testid="stDataFrame"] { border-radius: var(--radius); overflow: hidden; }

    /* ---------------- Chips ---------------- */
    .gmfcf-chip {
        display: inline-block; font-size: 0.75rem; font-weight: 500;
        padding: 0.24rem 0.62rem; border-radius: 7px;
        margin: 0 0.3rem 0.4rem 0; border: 1px solid var(--line);
        background: var(--surface-2); color: var(--ink-soft);
    }
    .gmfcf-chip.accent {
        background: var(--accent-bg); color: var(--accent); border-color: transparent;
    }

    .gmfcf-empty {
        color: var(--ink-faint); font-size: 0.9rem; padding: 1.4rem 0;
        border: 1px dashed var(--line); border-radius: var(--radius);
        text-align: center; margin-top: 0.5rem;
    }

    /* ---------------- Sidebar ---------------- */
    [data-testid="stSidebar"] {
        background: var(--surface-2); border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] .block-container { padding-top: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def chip(text: str, accent: bool = False) -> str:
    return f'<span class="gmfcf-chip{" accent" if accent else ""}">{text}</span>'


def section_label(text: str, top: str = "0") -> None:
    st.markdown(
        f'<p class="gmfcf-label" style="margin-top:{top};">{text}</p>',
        unsafe_allow_html=True,
    )


def empty_state(text: str) -> None:
    st.markdown(f'<div class="gmfcf-empty">{text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached wrappers — pure core/ functions stay Streamlit-free; caching lives
# only at this boundary so tests never depend on a Streamlit runtime.
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def cached_discover_department_pages(official_url: str, terms: tuple[str, ...]):
    return discover_department_pages(official_url, list(terms))


@st.cache_data(show_spinner=False, ttl=1800)
def cached_discover_faculty_roster(
    department_urls: tuple[str, ...],
    official_url: str,
    terms: tuple[str, ...],
    max_pages: int,
    delay_seconds: float,
):
    return discover_faculty_roster(list(department_urls), official_url, list(terms), max_pages, delay_seconds)


# ---------------------------------------------------------------------------
# Hero / input form
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="gmfcf-hero">
        <span class="gmfcf-kicker">Faculty-roster-first · Phase 5</span>
        <h1>Global Medical Faculty&nbsp;Contact Finder</h1>
        <p>Finds the official department, builds an approved faculty roster from
        official sources, then extracts only visible, verified institutional
        emails. Accuracy over quantity — nothing is guessed.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# st.container(border=True) is used rather than a raw <div> wrapper: Streamlit
# renders widgets outside injected HTML, so a hand-rolled card div paints an
# empty box instead of framing the inputs.
with st.container(border=True):
    section_label("Institution")
    left, right = st.columns(2, gap="large")
    with left:
        institution_name = st.text_input(
            "Institution name",
            placeholder="Stanford University School of Medicine",
        )
        official_url = st.text_input(
            "Official website URL",
            placeholder="https://med.stanford.edu",
        )
    with right:
        specialty = st.selectbox("Medical specialty or department", SPECIALTIES)
        custom_keywords = st.text_area(
            "Additional keywords — extends, never replaces the department",
            placeholder="Neonatology, Child Health",
            height=88,
        )
    st.write("")
    run_clicked = st.button(
        "Discover department and faculty",
        type="primary",
        use_container_width=True,
    )

with st.sidebar:
    section_label("Crawl settings")
    max_department_results = st.slider("Department candidates to use", 1, 10, 5)
    max_pages = st.slider("Max department / faculty pages", 10, 150, 50, 10)
    max_profiles = st.slider("Max individual profiles", 10, 200, 60, 10)
    delay_seconds = st.slider("Delay between requests (seconds)", 0.2, 2.0, 0.7, 0.1)
    st.caption("A lower delay is faster but puts more load on the institution's server.")

    section_label("Rules in force", top="2rem")
    st.markdown(
        chip("Roster before email", accent=True)
        + chip("Official domains only")
        + chip("No guessed addresses")
        + chip("Admin contacts rejected"),
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

if run_clicked:
    if not institution_name.strip():
        st.error("Please enter the institution name.")
        st.stop()

    normalized_official_url = normalize_url(official_url.strip())
    if not normalized_official_url:
        st.error("Please enter a valid official website URL.")
        st.stop()

    terms = resolve_terms(specialty, custom_keywords)
    if not terms:
        st.error("Please select a specialty or enter custom keywords.")
        st.stop()

    official_host = host_of(normalized_official_url)
    institution = institution_name.strip()

    status = st.status("Step 1 of 4 — Discovering the official department page…", expanded=True)
    with status:
        department_candidates, discovery_log = cached_discover_department_pages(
            normalized_official_url, tuple(terms)
        )
        st.write(f"Found {len(department_candidates)} candidate department page(s).")

    if not department_candidates:
        status.update(label="No relevant department page found.", state="error")
        st.error(
            "No relevant department page was found. The institution may use a different "
            "domain, JavaScript-rendered navigation, or unusual naming."
        )
        with st.expander("Department discovery log"):
            st.code("\n".join(discovery_log) or "No log entries.")
        st.stop()

    chosen_department_urls = [c.url for c in department_candidates[:max_department_results]]
    adapter_urls = run_adapters(
        DEFAULT_ADAPTERS, official_host, [c.url for c in department_candidates]
    )
    for adapter_url in adapter_urls:
        if adapter_url not in chosen_department_urls:
            chosen_department_urls.insert(0, adapter_url)

    status.update(label="Step 2 of 4 — Building the approved faculty roster…", state="running")
    with status:
        if adapter_urls:
            st.write(f"Institution-specific adapter contributed {len(adapter_urls)} directory URL(s).")
        (
            roster_entries,
            faculty_pages,
            role_rejections,
            crawl_log,
            page_html_cache,
        ) = cached_discover_faculty_roster(
            tuple(chosen_department_urls),
            normalized_official_url,
            tuple(terms),
            max_pages,
            delay_seconds,
        )
        st.write(f"Approved roster: {len(roster_entries)} faculty member(s).")

    if not roster_entries:
        status.update(label="No strict faculty roster could be built.", state="error")
        st.error(
            "No strict faculty roster could be built from official pages. Contact extraction "
            "was stopped to avoid returning staff or non-faculty records."
        )
        with st.expander("Department discovery log"):
            st.code("\n".join(discovery_log) or "No log entries.")
        with st.expander("Faculty crawl log"):
            st.code("\n".join(crawl_log) or "No log entries.")
        st.stop()

    roster_names = {entry.normalized_name for entry in roster_entries}
    roster_by_name = {entry.normalized_name: entry for entry in roster_entries}

    status.update(label="Step 3 of 4 — Opening individual faculty profiles…", state="running")
    with status:
        profile_links = discover_profile_links(page_html_cache, official_host, roster_names)
        profile_contacts, profile_rejections, profile_log = crawl_individual_profiles(
            profile_links=profile_links,
            official_host=official_host,
            roster_names=roster_names,
            institution=institution,
            department=specialty,
            max_profiles=max_profiles,
            delay_seconds=delay_seconds,
        )
        for contact in profile_contacts:
            entry = roster_by_name.get(normalize_person_name(contact.name))
            if entry:
                contact.faculty_title = entry.title
                contact.division_or_unit = entry.division
                contact.roster_source_url = entry.roster_source_url
        st.write(f"Inspected {len(profile_log)} profile page(s); {len(profile_contacts)} verified email(s).")

    covered_names = {normalize_person_name(c.name) for c in profile_contacts}
    card_contacts, card_rejections = extract_card_level_contacts(
        roster_entries=roster_entries,
        page_html_cache=page_html_cache,
        official_host=official_host,
        institution=institution,
        department=specialty,
        already_covered=covered_names,
    )

    status.update(label="Step 4 of 4 — Deduplicating and finalizing…", state="running")
    with status:
        all_contacts_raw = profile_contacts + card_contacts
        dedup_contacts = deduplicate_contacts(all_contacts_raw)

        all_rejections = role_rejections + profile_rejections + card_rejections

        covered_final = {normalize_person_name(c.name) for c in dedup_contacts}
        faculty_with_no_public_email = sum(
            1 for entry in roster_entries if entry.normalized_name not in covered_final
        )

        final_contacts: list[Contact] = dedup_contacts
        generic_fallback_used = False
        if not final_contacts:
            fallback = find_generic_department_email(chosen_department_urls, official_host, terms)
            if fallback:
                email, source_url = fallback
                final_contacts = [build_fallback_contact(email, source_url, institution, specialty)]
                generic_fallback_used = True

        st.write(f"Finalized {len(final_contacts)} record(s).")
        status.update(label="Done.", state="complete")

    summary = RunSummary(
        department_candidates_found=len(department_candidates),
        faculty_roster_entries_found=len(roster_entries),
        profiles_inspected=len(profile_log),
        verified_personal_emails=len(dedup_contacts),
        records_rejected=len(all_rejections),
        faculty_with_no_public_email=faculty_with_no_public_email,
        generic_fallback_used=generic_fallback_used,
    )

    unreachable_pages = [line for line in crawl_log if line.startswith("Could not access:")]
    unreachable_pages += [
        f"{entry.url} — {entry.detail}" if entry.detail else entry.url
        for entry in profile_log
        if entry.status in ("Could not access", "Rejected")
    ]

    # -----------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------

    stats = [
        ("Departments", summary.department_candidates_found, False),
        ("Roster entries", summary.faculty_roster_entries_found, False),
        ("Profiles inspected", summary.profiles_inspected, False),
        ("Verified emails", summary.verified_personal_emails, True),
        ("Rejected", summary.records_rejected, False),
        ("No public email", summary.faculty_with_no_public_email, False),
        ("Fallback", "Yes" if summary.generic_fallback_used else "No", False),
    ]
    st.markdown(
        '<div class="gmfcf-stats">'
        + "".join(
            f'<div class="gmfcf-stat{" accent" if accent else ""}">'
            f'<div class="v">{value}</div><div class="k">{label}</div></div>'
            for label, value, accent in stats
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    tab_results, tab_discovery, tab_roster, tab_profiles, tab_audit = st.tabs(
        ["Verified contacts", "Discovery", "Approved roster", "Profiles", "Audit & logs"]
    )

    with tab_results:
        if final_contacts:
            for contact in final_contacts:
                contact.institution = institution
                contact.department = specialty
            contact_frame = pd.DataFrame([c.as_row() for c in final_contacts], columns=CSV_COLUMNS)
            st.dataframe(contact_frame, use_container_width=True, hide_index=True)
            st.download_button(
                "Download verified contacts CSV",
                data=contact_frame.to_csv(index=False).encode("utf-8"),
                file_name="verified_faculty_contacts.csv",
                mime="text/csv",
                use_container_width=True,
            )
            method_counts = contact_frame["Extraction Method"].value_counts().to_dict()
            st.markdown(
                " ".join(chip(f"{method} · {count}") for method, count in method_counts.items()),
                unsafe_allow_html=True,
            )
        else:
            empty_state(
                "Department and faculty pages were verified, but no publicly visible "
                "personal faculty email was found, and no generic department email "
                "was available for fallback."
            )

    with tab_discovery:
        section_label("Keywords used")
        st.markdown(" ".join(chip(term, accent=True) for term in terms), unsafe_allow_html=True)

        section_label("Department pages discovered", top="1.75rem")
        dept_frame = pd.DataFrame([c.as_row() for c in department_candidates])
        dept_frame.insert(0, "Selected", dept_frame["Department URL"].isin(chosen_department_urls))
        st.dataframe(dept_frame, use_container_width=True, hide_index=True)

        section_label("Faculty pages discovered", top="1.75rem")
        if faculty_pages:
            st.dataframe(pd.DataFrame({"Faculty Page URL": faculty_pages}), use_container_width=True, hide_index=True)
        else:
            empty_state("No dedicated faculty-page URLs were identified.")

    with tab_roster:
        section_label("Approved faculty roster")
        roster_frame = pd.DataFrame([e.as_row() for e in roster_entries])
        st.dataframe(roster_frame, use_container_width=True, hide_index=True)

    with tab_profiles:
        section_label("Individual profiles discovered")
        if profile_links:
            st.dataframe(pd.DataFrame(profile_links), use_container_width=True, hide_index=True)
        else:
            empty_state("No individual profile links were discovered.")

        section_label("Profile crawl log", top="1.75rem")
        if profile_log:
            st.dataframe(pd.DataFrame([e.as_row() for e in profile_log]), use_container_width=True, hide_index=True)
        else:
            empty_state("No individual profiles were opened.")

    with tab_audit:
        section_label("Rejected records with reasons")
        if all_rejections:
            st.dataframe(pd.DataFrame([r.as_row() for r in all_rejections]), use_container_width=True, hide_index=True)
        else:
            empty_state("No rejected records.")

        section_label("Pages that could not be accessed", top="1.75rem")
        if unreachable_pages:
            st.code("\n".join(unreachable_pages))
        else:
            empty_state("All discovered pages were reachable.")

        with st.expander("Department discovery log"):
            st.code("\n".join(discovery_log) or "No log entries.")
        with st.expander("Faculty roster crawl log"):
            st.code("\n".join(crawl_log) or "No log entries.")

st.divider()
st.caption(
    "Order: official institution → matching department → approved faculty roster → "
    "individual profile / directory card → verified visible institutional email."
)
