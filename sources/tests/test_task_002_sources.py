import re
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Deliberately explicit, not auto-slugified — see Decision 2 in
# tasks/TASK_002_SOURCES.md. Every heading in SOURCES.md must appear here,
# whether or not that source is currently approved.
SOURCE_NAME_BY_HEADING = {
    "eBay API": "ebay_api",
    "My own 2018–present buy/sell records, entered manually": "personal_records",
    "TipidPC": "tipidpc",
    "Carousell PH": "carousell_ph",
    'Philippine retailer list prices (the "new" depreciation anchor)': "retailer_list_prices",
    "Manual paste-a-listing capture": "manual_capture",
}


def _parse_sources_md_statuses():
    """Return {heading: status} for every numbered source section in SOURCES.md."""
    text = (REPO_ROOT / "SOURCES.md").read_text()
    statuses = {}
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading_line, _, body = section.partition("\n")
        heading_match = re.match(r"\d+\.\s*(.+)", heading_line.strip())
        if not heading_match:
            continue  # "Excluded sources" has no leading number
        status_match = re.search(r"\*\*Status:\*\*\s*(.+)", body)
        statuses[heading_match.group(1).strip()] = status_match.group(1).strip()
    return statuses


def test_source_can_be_created_with_all_fields_and_null_last_successful_fetch(db):
    """A Source can be created with base_url, terms_notes, a positive rate_limit, and a null last_successful_fetch."""
    from sources.models import Source

    source = Source.objects.create(
        name="test_full_source",
        base_url="https://example.invalid/api",
        terms_notes="test fixture terms notes",
        rate_limit=30,
    )
    source.refresh_from_db()
    assert source.last_successful_fetch is None


def test_source_name_must_be_unique(db):
    """The database rejects a second Source row with a name that already exists."""
    from sources.models import Source

    Source.objects.create(
        name="test_duplicate_source",
        base_url="https://example.invalid",
        terms_notes="test fixture",
        rate_limit=60,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Source.objects.create(
                name="test_duplicate_source",
                base_url="https://example.invalid",
                terms_notes="test fixture",
                rate_limit=60,
            )


def test_source_rate_limit_must_be_positive(db):
    """The database rejects a Source row with rate_limit <= 0."""
    from sources.models import Source

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Source.objects.create(
                name="test_nonpositive_rate_limit",
                base_url="https://example.invalid",
                terms_notes="test fixture",
                rate_limit=0,
            )


def test_source_rate_limit_can_be_null(db):
    """A Source with no automated fetching cadence can leave rate_limit null."""
    from sources.models import Source

    source = Source.objects.create(
        name="test_source_no_automated_cadence",
        base_url="",
        terms_notes="test fixture: no automated fetching to rate-limit",
        rate_limit=None,
    )
    source.refresh_from_db()
    assert source.rate_limit is None


def test_source_terms_notes_is_required(db):
    """The database rejects a Source row whose terms_notes is empty."""
    from sources.models import Source

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Source.objects.create(
                name="test_missing_terms_notes",
                base_url="https://example.invalid",
                terms_notes="",
                rate_limit=60,
            )


def test_approved_sources_in_sources_md_have_matching_source_rows(db):
    """Every source marked APPROVED in SOURCES.md, and no other, has a matching Source row with a null rate_limit."""
    from sources.models import Source

    statuses = _parse_sources_md_statuses()
    approved_headings = {h for h, s in statuses.items() if s == "APPROVED"}
    expected_names = {SOURCE_NAME_BY_HEADING[h] for h in approved_headings}
    actual_names = set(Source.objects.values_list("name", flat=True))
    assert actual_names == expected_names, (
        f"Source rows {actual_names!r} do not match SOURCES.md's APPROVED set {expected_names!r}"
    )
    assert all(
        rate_limit is None
        for rate_limit in Source.objects.filter(
            name__in=expected_names
        ).values_list("rate_limit", flat=True)
    ), "seeded sources have no automated fetching cadence, so rate_limit must be null"
