import importlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings


DATASET = "pricewatchph_demo_v1"
ENABLE_ENV = "PRICEWATCHPH_ENABLE_DEMO_DATA"
D1 = date(2026, 6, 15)
D2 = date(2026, 7, 15)
EXPECTED_OUTPUT = (
    "Demo data ready: dataset=pricewatchph_demo_v1 skus=2 aliases=4 "
    "raw_listings=16 listings=16 pricepoints=5 dealflags=2 unresolved=1\n"
)

ATLAS_IDENTITY = ("PriceWatchPH Demo", "Atlas GPU", "12GB")
BEACON_IDENTITY = ("PriceWatchPH Demo", "Beacon CPU", "8C16T")

ATLAS_CANONICAL = "PRICEWATCHPH DEMO // Atlas GPU 12GB"
ATLAS_ALTERNATE = "DEMO Atlas-GPU / 12 GB"
BEACON_CANONICAL = "PRICEWATCHPH DEMO // Beacon CPU 8C16T"
BEACON_ALTERNATE = "DEMO Beacon-CPU / 8C 16T"
UNRESOLVED_TITLE = "PRICEWATCHPH DEMO // Mystery Component Prototype"

SKU_EXPECTATIONS = {
    ATLAS_IDENTITY: {
        "category": "gpu",
        "launch_msrp": Decimal("40000.00"),
        "launch_date": date(2025, 1, 15),
    },
    BEACON_IDENTITY: {
        "category": "cpu",
        "launch_msrp": Decimal("25000.00"),
        "launch_date": date(2025, 2, 15),
    },
}

ALIAS_EXPECTATIONS = {
    ATLAS_CANONICAL: ATLAS_IDENTITY,
    ATLAS_ALTERNATE: ATLAS_IDENTITY,
    BEACON_CANONICAL: BEACON_IDENTITY,
    BEACON_ALTERNATE: BEACON_IDENTITY,
}

HISTORY_DAYS = (
    date(2026, 4, 27),
    date(2026, 5, 7),
    date(2026, 5, 17),
    date(2026, 5, 27),
    date(2026, 6, 5),
)


def _row(suffix, sku, condition, day, price, title):
    return {
        "suffix": suffix,
        "external_id": f"{DATASET}:{suffix}",
        "sku": sku,
        "condition": condition,
        "day": day,
        "price": Decimal(price),
        "title": title,
        "slug": suffix.replace(":", "-"),
    }


RAW_EXPECTATIONS = tuple(
    [
        _row(
            f"atlas:used:history:{number:02d}",
            ATLAS_IDENTITY,
            "used",
            day,
            price,
            ATLAS_CANONICAL if number % 2 else ATLAS_ALTERNATE,
        )
        for number, (day, price) in enumerate(
            zip(HISTORY_DAYS, ("10000.00", "11000.00", "12000.00", "13000.00", "14000.00")),
            start=1,
        )
    ]
    + [
        _row(
            "atlas:used:ordinary:d1",
            ATLAS_IDENTITY,
            "used",
            D1,
            "12500.00",
            ATLAS_ALTERNATE,
        ),
        _row(
            "atlas:used:deal:d2",
            ATLAS_IDENTITY,
            "used",
            D2,
            "9250.00",
            ATLAS_CANONICAL,
        ),
        _row(
            "atlas:new:history:01",
            ATLAS_IDENTITY,
            "new",
            date(2026, 7, 5),
            "16000.00",
            ATLAS_ALTERNATE,
        ),
    ]
    + [
        _row(
            f"beacon:like_new:history:{number:02d}",
            BEACON_IDENTITY,
            "like_new",
            day,
            price,
            BEACON_CANONICAL if number % 2 else BEACON_ALTERNATE,
        )
        for number, (day, price) in enumerate(
            zip(HISTORY_DAYS, ("20000.00", "21000.00", "22000.00", "23000.00", "24000.00")),
            start=1,
        )
    ]
    + [
        _row(
            "beacon:like_new:ordinary:d1",
            BEACON_IDENTITY,
            "like_new",
            D1,
            "22500.00",
            BEACON_ALTERNATE,
        ),
        _row(
            "beacon:like_new:deal:d2",
            BEACON_IDENTITY,
            "like_new",
            D2,
            "19250.00",
            BEACON_CANONICAL,
        ),
        _row(
            "unresolved:mystery:d2",
            None,
            "used",
            D2,
            "9999.00",
            UNRESOLVED_TITLE,
        ),
    ]
)

RAW_BY_EXTERNAL_ID = {row["external_id"]: row for row in RAW_EXPECTATIONS}

PRICEPOINT_EXPECTATIONS = {
    (ATLAS_IDENTITY, "used", D1): {
        "n_listings": 5,
        "median": Decimal("12000.0000"),
        "p25": Decimal("11000.0000"),
        "p75": Decimal("13000.0000"),
        "mad": Decimal("1000.0000"),
    },
    (BEACON_IDENTITY, "like_new", D1): {
        "n_listings": 5,
        "median": Decimal("22000.0000"),
        "p25": Decimal("21000.0000"),
        "p75": Decimal("23000.0000"),
        "mad": Decimal("1000.0000"),
    },
    (ATLAS_IDENTITY, "new", D2): {
        "n_listings": 1,
        "median": Decimal("16000.0000"),
        "p25": Decimal("16000.0000"),
        "p75": Decimal("16000.0000"),
        "mad": Decimal("0.0000"),
    },
    (ATLAS_IDENTITY, "used", D2): {
        "n_listings": 6,
        "median": Decimal("12250.0000"),
        "p25": Decimal("11250.0000"),
        "p75": Decimal("12875.0000"),
        "mad": Decimal("1000.0000"),
    },
    (BEACON_IDENTITY, "like_new", D2): {
        "n_listings": 6,
        "median": Decimal("22250.0000"),
        "p25": Decimal("21250.0000"),
        "p75": Decimal("22875.0000"),
        "mad": Decimal("1000.0000"),
    },
}

DEAL_EXPECTATIONS = {
    f"{DATASET}:atlas:used:deal:d2": (ATLAS_IDENTITY, "used"),
    f"{DATASET}:beacon:like_new:deal:d2": (BEACON_IDENTITY, "like_new"),
}


def _sku_identity(sku):
    return (sku.brand, sku.model, sku.variant)


def _run_bootstrap():
    stdout = StringIO()
    with override_settings(ENABLE_DEMO_DATA=True):
        call_command("bootstrap_demo_data", stdout=stdout)
    assert stdout.getvalue() == EXPECTED_OUTPUT


def _model_counts():
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    return {
        "skus": Sku.objects.count(),
        "aliases": SkuAlias.objects.count(),
        "raw_listings": RawListing.objects.count(),
        "listings": Listing.objects.count(),
        "pricepoints": PricePoint.objects.count(),
        "dealflags": DealFlag.objects.count(),
        "outcomes": Outcome.objects.count(),
    }


def _database_snapshot():
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint
    from sources.models import Source

    model_fields = (
        (Source, ("id", "name", "base_url", "terms_notes", "rate_limit", "last_successful_fetch")),
        (Sku, ("id", "brand", "model", "variant", "category", "launch_msrp", "launch_date")),
        (SkuAlias, ("id", "sku_id", "alias_text", "normalised_text", "source_of_truth", "created_at")),
        (
            RawListing,
            (
                "id",
                "source_id",
                "raw_title",
                "raw_price_text",
                "raw_price",
                "url",
                "seller",
                "fetched_at",
                "occurred_at",
                "external_id",
                "payload",
            ),
        ),
        (
            Listing,
            (
                "id",
                "raw_listing_id",
                "sku_id",
                "price",
                "condition",
                "location",
                "resolution_confidence",
                "resolution_method",
                "resolved_at",
                "reviewed_unresolved_at",
                "observed_at",
                "price_kind",
                "trade_side",
            ),
        ),
        (
            PricePoint,
            (
                "id",
                "sku_id",
                "condition",
                "day",
                "median",
                "p25",
                "p75",
                "n_listings",
                "mad",
                "window_start_day",
                "window_end_day",
                "calculated_at",
                "calculation_contract_version",
            ),
        ),
        (
            DealFlag,
            (
                "id",
                "listing_id",
                "score",
                "baseline_pricepoint_id",
                "reason",
                "flagged_at",
            ),
        ),
        (Outcome, tuple(field.name for field in Outcome._meta.concrete_fields)),
    )
    return {
        model._meta.label: tuple(model.objects.order_by("pk").values_list(*fields))
        for model, fields in model_fields
    }


def _create_resolver_subject(*, source_name, payload):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing
    from listings.normalisation import normalise_title
    from sources.models import Source

    sku = Sku.objects.create(
        brand=f"Resolver Demo {source_name}",
        model="Explicit Fact Subject",
        variant=str(Sku.objects.count()),
        category="gpu",
        launch_msrp=Decimal("1000.00"),
        launch_date=date(2025, 1, 1),
    )
    title = f"Resolver explicit fact {source_name} {sku.pk}"
    SkuAlias.objects.create(
        sku=sku,
        alias_text=title,
        normalised_text=normalise_title(title),
        source_of_truth="seed",
    )
    instant = datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc)
    raw = RawListing.objects.create(
        source=Source.objects.get(name=source_name),
        raw_title=title,
        raw_price_text="1000.00",
        raw_price=Decimal("1000.00"),
        url="https://pricewatchph-demo.invalid/resolver-subject/",
        seller="",
        fetched_at=instant,
        occurred_at=instant,
        external_id=f"resolver-subject-{source_name}-{sku.pk}",
        payload=payload,
    )
    return raw


@pytest.mark.parametrize(
    ("environment_value", "expected"),
    (
        (None, False),
        ("0", False),
        ("", False),
        ("true", False),
        ("TRUE", False),
        ("1", True),
    ),
)
def test_demo_enable_setting_accepts_only_literal_one(
    monkeypatch,
    environment_value,
    expected,
):
    from config import settings as settings_module

    if environment_value is None:
        monkeypatch.delenv(ENABLE_ENV, raising=False)
    else:
        monkeypatch.setenv(ENABLE_ENV, environment_value)
    importlib.reload(settings_module)
    try:
        assert settings_module.ENABLE_DEMO_DATA is expected
    finally:
        monkeypatch.undo()
        importlib.reload(settings_module)


def test_env_example_documents_demo_setting_disabled():
    env_example = Path(__file__).resolve().parent.parent / ".env.example"
    lines = {line.strip() for line in env_example.read_text().splitlines()}
    assert f"{ENABLE_ENV}=0" in lines


@pytest.mark.django_db
def test_disabled_command_fails_before_writing_any_database_state():
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=False):
        with pytest.raises(
            CommandError,
            match=re.escape(
                "Demo data bootstrap is disabled. "
                "Set PRICEWATCHPH_ENABLE_DEMO_DATA=1 to enable it."
            ),
        ):
            call_command("bootstrap_demo_data")

    assert _database_snapshot() == before


@pytest.mark.django_db
def test_enabled_command_requires_existing_manual_capture_source_and_creates_no_source():
    from sources.models import Source

    before_names = set(Source.objects.values_list("name", flat=True))
    Source.objects.get(name="manual_capture").delete()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(
            CommandError,
            match="Required approved Source manual_capture is missing",
        ):
            call_command("bootstrap_demo_data")

    assert set(Source.objects.values_list("name", flat=True)) == before_names - {
        "manual_capture"
    }


@pytest.mark.django_db
@pytest.mark.parametrize("option", ("--reset", "--delete", "--force"))
def test_command_has_no_destructive_mode_and_rejected_option_changes_nothing(option):
    _run_bootstrap()
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(
            CommandError,
            match=re.escape(f"unrecognized arguments: {option}"),
        ):
            call_command("bootstrap_demo_data", option)

    assert _database_snapshot() == before


@pytest.mark.django_db
def test_bootstrap_creates_exact_synthetic_catalogue_and_seed_aliases():
    from catalogue.models import Sku, SkuAlias
    from listings.normalisation import normalise_title

    _run_bootstrap()

    assert Sku.objects.count() == 2
    for sku in Sku.objects.all():
        identity = _sku_identity(sku)
        expected = SKU_EXPECTATIONS[identity]
        assert sku.category == expected["category"]
        assert sku.launch_msrp == expected["launch_msrp"]
        assert sku.launch_date == expected["launch_date"]
        assert "PriceWatchPH Demo" in sku.brand

    assert SkuAlias.objects.count() == 4
    for alias in SkuAlias.objects.select_related("sku"):
        assert alias.alias_text in ALIAS_EXPECTATIONS
        assert _sku_identity(alias.sku) == ALIAS_EXPECTATIONS[alias.alias_text]
        assert alias.normalised_text == normalise_title(alias.alias_text)
        assert alias.source_of_truth == "seed"


@pytest.mark.django_db
def test_bootstrap_creates_exact_immutable_manual_capture_observations():
    from ingestion.models import RawListing

    _run_bootstrap()

    rows = RawListing.objects.select_related("source").order_by("external_id")
    assert rows.count() == 16
    assert set(rows.values_list("external_id", flat=True)) == set(RAW_BY_EXTERNAL_ID)

    for raw in rows:
        expected = RAW_BY_EXTERNAL_ID[raw.external_id]
        price_text = f"{expected['price']:.2f}"
        occurred_at = datetime.combine(
            expected["day"],
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).replace(hour=4)
        fetched_at = occurred_at + timedelta(minutes=5)
        expected_url = (
            "https://pricewatchph-demo.invalid/listings/"
            f"{expected['slug']}/"
        )
        expected_payload = {
            "title": expected["title"],
            "price": price_text,
            "url": expected_url,
            "external_id": expected["external_id"],
            "stated_condition": expected["condition"],
            "stated_price_kind": "asking",
        }

        assert raw.source.name == "manual_capture"
        assert raw.raw_title == expected["title"]
        assert raw.raw_price_text == price_text
        assert raw.raw_price == expected["price"]
        assert raw.url == expected_url
        assert raw.url.startswith("https://pricewatchph-demo.invalid/")
        assert raw.seller == ""
        assert raw.occurred_at == occurred_at
        assert raw.fetched_at == fetched_at
        assert raw.payload == expected_payload
        assert "seller" not in raw.payload


@pytest.mark.django_db
def test_bootstrap_preserves_all_preexisting_sources_and_source_health():
    from django.utils import timezone as django_timezone
    from ingestion.models import RawListing
    from sources.models import Source

    marker = django_timezone.now() - timedelta(days=1)
    Source.objects.filter(name="manual_capture").update(last_successful_fetch=marker)
    Source.objects.create(
        name="preexisting_unrelated_source",
        base_url="https://preexisting-source.invalid/",
        terms_notes="Pre-existing source outside the TASK_027 command's ownership.",
        rate_limit=17,
        last_successful_fetch=marker - timedelta(hours=1),
    )
    source_fields = (
        "id",
        "name",
        "base_url",
        "terms_notes",
        "rate_limit",
        "last_successful_fetch",
    )
    before = tuple(Source.objects.order_by("pk").values_list(*source_fields))

    _run_bootstrap()

    assert tuple(Source.objects.order_by("pk").values_list(*source_fields)) == before
    assert not RawListing.objects.filter(source__name="personal_records").exists()
    assert RawListing.objects.filter(source__name="manual_capture").count() == 16


@pytest.mark.django_db
def test_bootstrap_resolves_exact_aliases_and_leaves_one_honest_review_row():
    from listings.models import Listing

    _run_bootstrap()

    assert Listing.objects.count() == 16
    resolved = Listing.objects.exclude(sku=None)
    assert resolved.count() == 15
    assert set(resolved.values_list("resolution_method", flat=True)) == {"exact_alias"}
    assert set(resolved.values_list("resolution_confidence", flat=True)) == {
        Decimal("1.0000")
    }

    for listing in Listing.objects.select_related("raw_listing", "sku"):
        expected = RAW_BY_EXTERNAL_ID[listing.raw_listing.external_id]
        assert listing.price == expected["price"]
        assert listing.condition == expected["condition"]
        assert listing.location == ""
        assert listing.observed_at == listing.raw_listing.occurred_at
        assert listing.price_kind == "asking"
        assert listing.trade_side is None
        if expected["sku"] is None:
            assert listing.sku is None
            assert listing.resolution_method == "unresolved"
            assert listing.resolution_confidence == Decimal("0.0000")
            assert listing.reviewed_unresolved_at is None
        else:
            assert _sku_identity(listing.sku) == expected["sku"]

    queue = Listing.objects.filter(
        sku__isnull=True,
        reviewed_unresolved_at__isnull=True,
    )
    assert queue.count() == 1
    assert queue.get().raw_listing.external_id == f"{DATASET}:unresolved:mystery:d2"


@pytest.mark.django_db
def test_manual_capture_exact_asking_fact_is_trusted_by_resolver():
    from listings.resolver import resolve_raw_listing

    raw = _create_resolver_subject(
        source_name="manual_capture",
        payload={
            "stated_condition": "used",
            "stated_price_kind": "asking",
        },
    )

    listing = resolve_raw_listing(raw)

    assert listing.price_kind == "asking"
    assert listing.trade_side is None


@pytest.mark.django_db
def test_manual_capture_source_name_without_explicit_fact_keeps_price_kind_null():
    from listings.resolver import resolve_raw_listing

    raw = _create_resolver_subject(
        source_name="manual_capture",
        payload={"stated_condition": "used"},
    )

    listing = resolve_raw_listing(raw)

    assert listing.price_kind is None
    assert listing.trade_side is None


@pytest.mark.django_db
def test_another_source_cannot_supply_the_new_asking_fact():
    from listings.resolver import resolve_raw_listing

    raw = _create_resolver_subject(
        source_name="personal_records",
        payload={
            "stated_condition": "used",
            "stated_price_kind": "asking",
        },
    )

    listing = resolve_raw_listing(raw)

    assert listing.price_kind is None
    assert listing.trade_side is None


@pytest.mark.django_db
def test_trade_side_fact_takes_realised_precedence_over_stated_asking():
    from listings.resolver import resolve_raw_listing

    raw = _create_resolver_subject(
        source_name="manual_capture",
        payload={
            "stated_condition": "used",
            "stated_price_kind": "asking",
            "stated_trade_side": "buy",
        },
    )

    listing = resolve_raw_listing(raw)

    assert listing.price_kind == "realised"
    assert listing.trade_side == "buy"


@pytest.mark.django_db
@pytest.mark.parametrize("unsupported", ["realised", "ASKING", "unknown", True, 1])
def test_unsupported_explicit_price_kind_values_remain_untrusted(unsupported):
    from listings.resolver import resolve_raw_listing

    raw = _create_resolver_subject(
        source_name="manual_capture",
        payload={
            "stated_condition": "used",
            "stated_price_kind": unsupported,
        },
    )

    listing = resolve_raw_listing(raw)

    assert listing.price_kind is None
    assert listing.trade_side is None


@pytest.mark.django_db
def test_ordinary_ingest_manual_capture_remains_unclassified_and_rejects_override(monkeypatch):
    from ingestion.models import RawListing
    from listings.resolver import resolve_raw_listing

    ordinary = {
        "title": "Ordinary manual capture remains unchanged",
        "price": "12345.00",
        "external_id": "ordinary-task-027-control",
    }
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(ordinary)))
    call_command("ingest", "manual_capture")
    raw = RawListing.objects.get(external_id="ordinary-task-027-control")
    listing = resolve_raw_listing(raw)

    assert raw.occurred_at is None
    assert listing.condition is None
    assert listing.price_kind is None
    assert listing.trade_side is None

    attempted_override = {
        "title": "Manual capture override must remain closed",
        "price": "12345.00",
        "external_id": "ordinary-task-027-rejected",
        "stated_price_kind": "asking",
    }
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(attempted_override)))
    with pytest.raises(CommandError, match="unknown field"):
        call_command("ingest", "manual_capture")

    assert not RawListing.objects.filter(
        external_id="ordinary-task-027-rejected"
    ).exists()


@pytest.mark.django_db
def test_fixed_utc_instants_map_to_manifest_manila_days_and_windows():
    from ingestion.models import RawListing
    from pricing.bucketing import manila_day
    from pricing.models import PricePoint

    _run_bootstrap()

    for raw in RawListing.objects.all():
        expected = RAW_BY_EXTERNAL_ID[raw.external_id]
        expected_instant = datetime.combine(
            expected["day"],
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).replace(hour=4)
        assert raw.occurred_at == expected_instant
        assert manila_day(raw.occurred_at) == expected["day"]

    persisted_windows = set(
        PricePoint.objects.values_list(
            "day",
            "window_start_day",
            "window_end_day",
        )
    )
    assert persisted_windows == {
        (D1, date(2026, 3, 17), D1),
        (D2, date(2026, 4, 16), D2),
    }


@pytest.mark.django_db
def test_bootstrap_persists_exact_history_condition_and_same_day_baselines():
    from pricing.models import PricePoint

    _run_bootstrap()

    assert PricePoint.objects.count() == 5
    for pricepoint in PricePoint.objects.select_related("sku"):
        key = (_sku_identity(pricepoint.sku), pricepoint.condition, pricepoint.day)
        expected = PRICEPOINT_EXPECTATIONS[key]
        assert pricepoint.n_listings == expected["n_listings"]
        assert pricepoint.median == expected["median"]
        assert pricepoint.p25 == expected["p25"]
        assert pricepoint.p75 == expected["p75"]
        assert pricepoint.mad == expected["mad"]
        assert pricepoint.window_start_day == pricepoint.day - timedelta(days=90)
        assert pricepoint.window_end_day == pricepoint.day
        assert pricepoint.calculated_at is not None
        assert pricepoint.calculated_at.utcoffset() == timedelta(0)
        assert pricepoint.calculation_contract_version == "asking_price_baseline_v1"

    atlas_used_d1 = PricePoint.objects.get(
        sku__brand=ATLAS_IDENTITY[0],
        sku__model=ATLAS_IDENTITY[1],
        sku__variant=ATLAS_IDENTITY[2],
        condition="used",
        day=D1,
    )
    atlas_used_d2 = PricePoint.objects.get(
        sku__brand=ATLAS_IDENTITY[0],
        sku__model=ATLAS_IDENTITY[1],
        sku__variant=ATLAS_IDENTITY[2],
        condition="used",
        day=D2,
    )
    assert atlas_used_d1.n_listings == 5
    assert atlas_used_d2.n_listings == 6
    assert atlas_used_d1.median == Decimal("12000.0000")
    assert atlas_used_d2.median == Decimal("12250.0000")
    assert atlas_used_d1.mad == atlas_used_d2.mad == Decimal("1000.0000")

    # These distinct outputs prove D1's target was excluded from D1, included
    # in D2, and D2's target was excluded from D2.
    assert RAW_BY_EXTERNAL_ID[
        f"{DATASET}:atlas:used:ordinary:d1"
    ]["price"] == Decimal("12500.00")
    assert RAW_BY_EXTERNAL_ID[
        f"{DATASET}:atlas:used:deal:d2"
    ]["price"] == Decimal("9250.00")


@pytest.mark.django_db
def test_bootstrap_scores_ordinary_and_deal_observations_through_persisted_evidence():
    from ingestion.models import RawListing
    from pricing.models import DealFlag
    from pricing.scoring import score_listing

    _run_bootstrap()

    assert DealFlag.objects.count() == 2
    actual_deal_external_ids = set()
    for flag in DealFlag.objects.select_related(
        "listing__raw_listing",
        "baseline_pricepoint__sku",
    ):
        external_id = flag.listing.raw_listing.external_id
        actual_deal_external_ids.add(external_id)
        expected_sku, expected_condition = DEAL_EXPECTATIONS[external_id]
        assert _sku_identity(flag.baseline_pricepoint.sku) == expected_sku
        assert flag.baseline_pricepoint.condition == expected_condition
        assert flag.baseline_pricepoint.day == D2
        assert flag.score == Decimal("-3.0000")
        assert flag.reason == "asking_price_mad_v1"
        assert flag.flagged_at is not None
        assert flag.flagged_at.utcoffset() == timedelta(0)
    assert actual_deal_external_ids == set(DEAL_EXPECTATIONS)

    for external_id in (
        f"{DATASET}:atlas:used:ordinary:d1",
        f"{DATASET}:beacon:like_new:ordinary:d1",
    ):
        listing = RawListing.objects.get(external_id=external_id).listing
        assert score_listing(listing=listing) is None
        assert not DealFlag.objects.filter(listing=listing).exists()


@pytest.mark.django_db
def test_bootstrap_creates_no_outcome_and_pricing_replays_are_noops():
    from outcomes.models import Outcome

    _run_bootstrap()
    before = _database_snapshot()

    call_command("price_listings", day=D1.isoformat(), stdout=StringIO())
    call_command("price_listings", day=D2.isoformat(), stdout=StringIO())

    assert Outcome.objects.count() == 0
    assert _database_snapshot() == before


@pytest.mark.django_db
def test_bootstrapped_evidence_is_visible_through_existing_product_apis(client, django_user_model):
    from catalogue.models import Sku

    _run_bootstrap()
    user = django_user_model.objects.create_superuser(
        username="task027-product-reader",
        password="test-password",
        email="",
    )
    client.force_login(user)

    deals = client.get("/api/v1/deal-flags/")
    assert deals.status_code == 200
    assert deals.json()["count"] == 2
    assert {item["score"] for item in deals.json()["results"]} == {"-3.0000"}

    atlas = Sku.objects.get(
        brand=ATLAS_IDENTITY[0],
        model=ATLAS_IDENTITY[1],
        variant=ATLAS_IDENTITY[2],
    )
    history = client.get(f"/api/v1/skus/{atlas.pk}/price-points/")
    assert history.status_code == 200
    assert history.json()["count"] == 3
    assert [(item["day"], item["condition"]) for item in history.json()["results"]] == [
        ("2026-06-15", "used"),
        ("2026-07-15", "new"),
        ("2026-07-15", "used"),
    ]

    used_history = client.get(
        f"/api/v1/skus/{atlas.pk}/price-points/",
        {"condition": "used"},
    )
    assert used_history.status_code == 200
    assert used_history.json()["count"] == 2

    reviews = client.get("/api/v1/reviews/listings/")
    assert reviews.status_code == 200
    assert reviews.json()["count"] == 1
    review = reviews.json()["results"][0]
    assert review["raw_evidence"]["raw_title"] == UNRESOLVED_TITLE
    assert review["raw_evidence"]["source"]["name"] == "manual_capture"
    assert review["derived_listing"]["price_kind"] == "asking"


@pytest.mark.django_db
def test_unchanged_second_run_is_an_exact_persisted_noop():
    _run_bootstrap()
    before = _database_snapshot()

    _run_bootstrap()

    assert _database_snapshot() == before
    assert _model_counts() == {
        "skus": 2,
        "aliases": 4,
        "raw_listings": 16,
        "listings": 16,
        "pricepoints": 5,
        "dealflags": 2,
        "outcomes": 0,
    }


@pytest.mark.django_db
def test_conflicting_sku_identity_fails_atomically_without_repair():
    from catalogue.models import Sku

    conflicting = Sku.objects.create(
        brand=ATLAS_IDENTITY[0],
        model=ATLAS_IDENTITY[1],
        variant=ATLAS_IDENTITY[2],
        category="cpu",
        launch_msrp=Decimal("40000.00"),
        launch_date=date(2025, 1, 15),
    )
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(CommandError, match="Conflicting demo Sku identity"):
            call_command("bootstrap_demo_data")

    conflicting.refresh_from_db()
    assert conflicting.category == "cpu"
    assert _database_snapshot() == before


@pytest.mark.django_db
def test_conflicting_rawlisting_logical_identity_rolls_back_earlier_creates():
    from ingestion.models import RawListing
    from sources.models import Source

    conflict_id = f"{DATASET}:atlas:used:history:01"
    RawListing.objects.create(
        source=Source.objects.get(name="manual_capture"),
        raw_title="Conflicting pre-existing immutable title",
        raw_price_text="1.00",
        raw_price=Decimal("1.00"),
        url="https://pricewatchph-demo.invalid/conflict/",
        seller="",
        fetched_at=datetime(2026, 4, 27, 4, 5, tzinfo=timezone.utc),
        occurred_at=datetime(2026, 4, 27, 4, 0, tzinfo=timezone.utc),
        external_id=conflict_id,
        payload={},
    )
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(CommandError, match="Conflicting demo RawListing identity"):
            call_command("bootstrap_demo_data")

    assert _database_snapshot() == before


@pytest.mark.django_db
def test_duplicate_rawlisting_logical_identity_fails_without_creating_a_third_row():
    from ingestion.models import RawListing
    from sources.models import Source

    source = Source.objects.get(name="manual_capture")
    conflict_id = f"{DATASET}:atlas:used:history:01"
    for minute, title in (
        (5, "First conflicting immutable observation"),
        (6, "Second conflicting immutable observation"),
    ):
        RawListing.objects.create(
            source=source,
            raw_title=title,
            raw_price_text="1.00",
            raw_price=Decimal("1.00"),
            url=f"https://pricewatchph-demo.invalid/conflict/{minute}/",
            seller="",
            fetched_at=datetime(2026, 4, 27, 4, minute, tzinfo=timezone.utc),
            occurred_at=datetime(2026, 4, 27, 4, 0, tzinfo=timezone.utc),
            external_id=conflict_id,
            payload={"conflict": minute},
        )
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(CommandError, match="Conflicting demo RawListing identity"):
            call_command("bootstrap_demo_data")

    assert RawListing.objects.filter(
        source=source,
        external_id=conflict_id,
    ).count() == 2
    assert _database_snapshot() == before


@pytest.mark.django_db
def test_changed_demo_listing_is_reported_and_not_repaired():
    from ingestion.models import RawListing
    from listings.models import Listing

    _run_bootstrap()
    listing = RawListing.objects.get(
        external_id=f"{DATASET}:atlas:used:ordinary:d1"
    ).listing
    Listing.objects.filter(pk=listing.pk).update(price=Decimal("1.00"))
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(CommandError, match="Conflicting demo Listing identity"):
            call_command("bootstrap_demo_data")

    listing.refresh_from_db()
    assert listing.price == Decimal("1.00")
    assert _database_snapshot() == before


@pytest.mark.django_db
def test_conflicting_sealed_pricepoint_is_reported_and_not_replaced():
    from catalogue.models import Sku
    from django.utils import timezone as django_timezone
    from pricing.models import PricePoint

    atlas = Sku.objects.create(
        brand=ATLAS_IDENTITY[0],
        model=ATLAS_IDENTITY[1],
        variant=ATLAS_IDENTITY[2],
        **SKU_EXPECTATIONS[ATLAS_IDENTITY],
    )
    conflicting = PricePoint.objects.create(
        sku=atlas,
        condition="used",
        day=D1,
        median=Decimal("2.0000"),
        p25=Decimal("1.0000"),
        p75=Decimal("3.0000"),
        n_listings=5,
        mad=Decimal("1.0000"),
        window_start_day=D1 - timedelta(days=90),
        window_end_day=D1,
        calculated_at=django_timezone.now(),
        calculation_contract_version="asking_price_baseline_v1",
    )
    before = _database_snapshot()

    with override_settings(ENABLE_DEMO_DATA=True):
        with pytest.raises(CommandError, match="Conflicting demo PricePoint identity"):
            call_command("bootstrap_demo_data")

    conflicting.refresh_from_db()
    assert conflicting.median == Decimal("2.0000")
    assert _database_snapshot() == before
