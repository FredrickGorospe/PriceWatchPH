from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, ProgrammingError, transaction
from django.utils import timezone


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name="test_source",
        base_url="https://example.invalid",
        terms_notes="test fixture",
        rate_limit=None,
    )


def test_rawlisting_can_be_created_with_all_fields(source):
    """A RawListing can be created with source, raw_title, raw_price_text, raw_price, url, seller, fetched_at, external_id."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="ASUS TUF RTX 4070 12GB",
        raw_price_text="15,500",
        raw_price=Decimal("15500.00"),
        url="https://example.invalid/x",
        seller="juan_dela_cruz",
        fetched_at=timezone.now(),
        external_id="abc123",
    )
    listing.refresh_from_db()
    assert listing.raw_price == Decimal("15500.00")


def test_rawlisting_raw_price_can_be_null_when_unparseable(source):
    """An unparseable price is preserved via raw_price_text with raw_price left null, rather than the row being dropped."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="RTX 4070 - PM for price",
        raw_price_text="PM for price",
        raw_price=None,
        url="https://example.invalid/y",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    listing.refresh_from_db()
    assert listing.raw_price is None
    assert listing.raw_price_text == "PM for price"


def test_rawlisting_raw_price_must_be_non_negative(source):
    """The database rejects a RawListing row with a negative raw_price."""
    from ingestion.models import RawListing

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RawListing.objects.create(
                source=source,
                raw_title="x",
                raw_price_text="-5",
                raw_price=Decimal("-5.00"),
                url="https://example.invalid/z",
                seller="anon",
                fetched_at=timezone.now(),
                external_id=None,
            )


def test_rawlisting_external_id_can_repeat_when_null(source):
    """Two RawListing rows for the same source and fetched_at with a null external_id are both allowed — the idempotency key only applies when external_id is present."""
    from ingestion.models import RawListing

    now = timezone.now()
    RawListing.objects.create(
        source=source,
        raw_title="a",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/a",
        seller="anon",
        fetched_at=now,
        external_id=None,
    )
    RawListing.objects.create(
        source=source,
        raw_title="b",
        raw_price_text="200",
        raw_price=Decimal("200.00"),
        url="https://example.invalid/b",
        seller="anon",
        fetched_at=now,
        external_id=None,
    )
    assert RawListing.objects.filter(source=source, fetched_at=now).count() == 2


def test_rawlisting_source_external_id_fetched_at_must_be_unique_when_external_id_present(source):
    """The database rejects a second RawListing row with the same (source, external_id, fetched_at) when external_id is not null."""
    from ingestion.models import RawListing

    now = timezone.now()
    RawListing.objects.create(
        source=source,
        raw_title="a",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/a",
        seller="anon",
        fetched_at=now,
        external_id="dup-id",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RawListing.objects.create(
                source=source,
                raw_title="a again",
                raw_price_text="100",
                raw_price=Decimal("100.00"),
                url="https://example.invalid/a",
                seller="anon",
                fetched_at=now,
                external_id="dup-id",
            )


def test_rawlisting_save_raises_on_update_via_model(source):
    """Calling .save() on an already-persisted RawListing raises before reaching the database — Option A's application-level guard."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="x",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    listing.raw_title = "changed"
    with pytest.raises(ValidationError):
        listing.save()


def test_rawlisting_delete_raises_via_model(source):
    """Calling .delete() on a RawListing raises before reaching the database — Option A's application-level guard."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="x",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    with pytest.raises(ValidationError):
        listing.delete()


def test_rawlisting_queryset_update_is_blocked_at_the_database(source):
    """QuerySet.update() bypasses the model's save() override entirely, so the guarantee must come from the database trigger (Option B) — the acceptance question TASK_003 exists to answer."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="x",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            RawListing.objects.filter(pk=listing.pk).update(raw_title="changed via queryset")


def test_rawlisting_queryset_delete_is_blocked_at_the_database(source):
    """QuerySet.delete() also bypasses the model's delete() override; the database trigger must block it too."""
    from ingestion.models import RawListing

    listing = RawListing.objects.create(
        source=source,
        raw_title="x",
        raw_price_text="100",
        raw_price=Decimal("100.00"),
        url="https://example.invalid/x",
        seller="anon",
        fetched_at=timezone.now(),
        external_id=None,
    )
    with pytest.raises(ProgrammingError):
        with transaction.atomic():
            RawListing.objects.filter(pk=listing.pk).delete()
