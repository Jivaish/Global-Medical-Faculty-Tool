# Global Medical Faculty Contact Finder — Phase 5

Identifies medical institutions' official department pages, builds a strict
**approved faculty roster**, and extracts only **visible, verified institutional
emails** for people on that roster.

This is not a general email scraper. Accuracy is prioritized over quantity, and
no email is ever guessed, generated, or inferred from a person's name.

No AI/LLM API is used anywhere — extraction is rule-based (HTTP + HTML parsing +
pattern matching), so there are no API keys to configure.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tests:

```bash
pip install -r requirements-dev.txt && python -m pytest tests/ -q
```

## Architecture

```
app.py                          Streamlit UI + orchestration only
core/
    models.py                   Dataclasses, CSV schema, RejectionReason vocabulary
    domains.py                  Official-domain verification, robots.txt parsing
    specialties.py              Per-department keyword registry
    crawler.py                  HTTP session, size caps, sitemaps, pagination
    department_discovery.py     Homepage / sitemap / common-path discovery
    roster_discovery.py         Paginated, title-gated roster construction
    faculty_validation.py       Name + academic-title validation
    profile_discovery.py        Profile discovery, parsing, card-level extraction
    email_validation.py         Visible-email extraction, obfuscation, context labels
    deduplication.py            Source-strength ranked merge
    fallback.py                 Generic department-contact rule
adapters/
    base.py                     Adapter protocol + runner
    stanford.py                 Isolated Stanford CAP / profiles handling
tests/                          61 unit + integration tests
```

## Validation sequence

1. **Domain verification** — resolve the official host and its organization root.
   Every later fetch and every accepted email must stay inside that family.
2. **Specialty keywords** — the selected department's terms, *extended* (never
   replaced) by any custom keywords.
3. **Department discovery** — homepage links ∪ sitemap URLs ∪ common paths. A
   candidate with zero specialty-term matches is **discarded at this point**, so
   unrelated departments never enter faculty extraction.
4. **Adapter injection** — institution-specific URLs added additively (Stanford
   only, gated on `stanford.edu`).
5. **Roster construction (roster-first)** — crawl candidates with pagination
   (`rel=next`, numbered pages), and for each person card:
   exclusion patterns are checked **first** and win over any allowed title.
   The approved roster is complete **before any email is read**.
6. **Profile discovery & parsing** — iterate **roster entries**, not pages. A
   profile's name must match the roster before its emails are considered.
7. **Card-level extraction** — for roster entries with no separate profile,
   pull an email from that person's own card only.
8. **Deduplication** — by normalized email, then name+institution+department,
   keeping: personal profile > directory card > department page.
9. **Generic fallback** — only if the roster is non-empty and zero personal
   emails were found; returns exactly one `Department Contact` row.

### Email acceptance rules

Accepted only if visibly displayed on an official institutional page and inside
the institution's domain family. Rejected: personal domains (gmail/yahoo/…),
generic mailboxes (`info@`, `contact@`, …), off-domain addresses, and — critically —
any address labelled as an **administrative or alternate contact**, which is how
an assistant's address otherwise gets attributed to a faculty member.

## Bugs fixed from the previous single-file version

| Bug | Effect | Fix |
|---|---|---|
| Contacts extracted *during* the crawl, roster applied afterwards as a filter | Not actually roster-first | Roster built fully before any email is read; extraction iterates roster entries |
| `NAME_RE` compiled with `re.IGNORECASE` | Disabled its own `[A-Z]` rule, so headings like "Current Research and Scholarly Interests" validated as names | Token-based `valid_name()` with explicit capitalization + stopword checks |
| Admin-context check applied to cards only, never to profile pages | Assistants' emails returned as faculty emails (real case: Stanford `ntefera@`, `tracyl@`, `delilas@`) | `extract_emails_with_context()` labels every email; admin-labelled addresses rejected |
| Role regex run against the whole ~1800-char card | Real professors excluded because their *bio* mentioned a fellowship | `extract_title_text()` scopes the role gate to title-like text |
| Multi-person containers treated as one card | First name paired with first email (real case: `Cooper Aakhus → aabai@`) | Containers with ≠1 person name are skipped |
| Substring matching (`"staff" in text`) | A professor named **Stafford** was rejected | `\b`-bounded regex throughout |
| `\bfellow\b` excluded unconditionally | "Fellow of the American College of Obstetricians" dropped attending professors | Credential phrasing carved out from the role pattern |
| Dedup was a bare `(name, email)` set | Weak sources could beat strong ones | `SOURCE_STRENGTH` ranked merge |
| No pagination | Everything past page 1 lost | `find_pagination_links()` + visited-set |
| Single rejection reason string | No audit detail | 16-value `RejectionReason` vocabulary |

## What is verified vs. uncertain

**Verified by tests (71 passing)** — specialty keyword resolution, email
validation and obfuscation decoding, admin-context detection, displayed-contact
vs. prose detection, name validation, title allow/deny gating, deduplication
ordering, generic-fallback classification, and a fixture-based end-to-end
roster→email run covering both accept and reject paths.

**Verified against live sites:**

- `med.stanford.edu`, Obstetrics and Gynecology — 8 department candidates,
  7 adapter URLs, an 88-person approved roster with correct titles, and
  specific rejections (Emeritus / Adjunct / Fellow). Stanford publishes **no**
  personal faculty emails: profile pages expose only an "Alternate Contact"
  administrative assistant (`ntefera@`, `tracyl@`, `bchargin@`) plus lab/tool
  addresses inside publication abstracts. The correct answer is therefore zero
  verified contacts, and that is what the app returns. Earlier builds returned
  those assistant addresses as faculty emails.
- `medicine.iu.edu`, Obstetrics and Gynecology — 15 department candidates,
  a 23-person roster (including `Lisa Landrum — Department Chair`), and one
  correctly attributed personal email: `Sara K. Quinney → squinney@iu.edu`.
  This confirms the accept path works end-to-end on a live site.

**Uncertain / not yet validated:**

- **Department scoping can over-collect.** The IU roster picked up faculty from
  neighbouring departments because IU's OB-GYN pages link out to a shared
  faculty directory. Names and titles are correct, but departmental membership
  is inferred from crawl proximity, not asserted by the source.
- **JavaScript-rendered directories are unsupported** by design (no Selenium).
  Several institutions tested returned nothing for this reason, and many sites
  block automated requests outright.
- **Division / Unit is frequently blank** — it is a heuristic extraction.
- **Recall is deliberately conservative.** An address only counts when it is a
  `mailto:` link or explicitly labelled; a real email printed bare in prose is
  rejected rather than risk misattribution.
- **The results view was verified visually before the final restyle**, and the
  pipeline itself was re-verified headlessly after it. The restyle changed only
  presentation (CSS, a custom stat grid in place of `st.metric`), not any
  extraction logic.

## Not yet implemented

The location cascade (Continent → Country → Region → Specialty → auto-populated
institution list) and multi-institution selection. Manual institution entry
remains, as agreed for this stage. The pipeline takes institution name + URL as
plain parameters, so multi-institution support is a loop over that call.
