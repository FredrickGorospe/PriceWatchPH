"""Frozen TASK_020 deterministic rolling PricePoint acceptance tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Context, Decimal, ROUND_UP, localcontext
from inspect import getsource
from itertools import count
import re
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext
from django.utils import timezone


AS_OF_DAY = date(2026, 8, 9)
MANILA = ZoneInfo("Asia/Manila")
CONTRACT_VERSION = "asking_price_baseline_v1"
_UNSET = object()


@pytest.fixture
def sku(db):
    from catalogue.models import Sku

    return Sku.objects.create(
        brand="Synthetic",
        model="TASK 020 GPU",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2026, 1, 1),
    )


@pytest.fixture
def source_factory(db):
    from sources.models import Source

    def make(name="task_020_source"):
        source, _ = Source.objects.get_or_create(
            name=name,
            defaults={
                "base_url": f"https://{name}.example.invalid",
                "terms_notes": "Synthetic TASK_020 fixture",
                "rate_limit": None,
            },
        )
        return source

    return make


def _manila_instant(day, *, hour=12, minute=0, second=0, microsecond=0):
    return datetime.combine(
        day,
        time(hour, minute, second, microsecond),
        tzinfo=MANILA,
    ).astimezone(dt_timezone.utc)


@pytest.fixture
def listing_factory(db, sku, source_factory):
    from ingestion.models import RawListing
    from listings.models import Listing

    sequence = count(1)

    def make(
        *,
        price=Decimal("100.00"),
        condition="used",
        observed_at=_UNSET,
        price_kind="asking",
        trade_side=None,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
        listing_sku=_UNSET,
        reviewed_unresolved_at=None,
        source_name="task_020_source",
        raw_title="Synthetic repeated-looking listing",
    ):
        number = next(sequence)
        source = source_factory(source_name)
        if observed_at is _UNSET:
            observed_at = _manila_instant(AS_OF_DAY - timedelta(days=1))
        selected_sku = sku if listing_sku is _UNSET else listing_sku
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=raw_title,
            raw_price_text="untrusted source text",
            raw_price=price,
            url=f"https://example.invalid/task-020/{number}",
            seller="seller_anon_token",
            fetched_at=_manila_instant(AS_OF_DAY - timedelta(days=1), hour=18),
            external_id=f"task-020-{number}",
            payload={"synthetic_fixture": number},
        )
        return Listing.objects.create(
            raw_listing=raw_listing,
            sku=selected_sku,
            price=price,
            condition=condition,
            location="",
            resolution_confidence=resolution_confidence,
            resolution_method=resolution_method,
            resolved_at=timezone.now(),
            observed_at=observed_at,
            price_kind=price_kind,
            trade_side=trade_side,
            reviewed_unresolved_at=reviewed_unresolved_at,
        )

    return make


def _build(sku, *, condition="used", as_of_day=AS_OF_DAY):
    from pricing.baselines import build_pricepoint

    return build_pricepoint(
        sku=sku,
        condition=condition,
        as_of_day=as_of_day,
    )


def _create_prices(listing_factory, prices, *, observed_at=None):
    for price in prices:
        kwargs = {"price": Decimal(price)}
        if observed_at is not None:
            kwargs["observed_at"] = observed_at
        listing_factory(**kwargs)


# --- Listing-fact eligibility ---------------------------------------------


@pytest.mark.parametrize("resolution_method", ["exact_alias", "human_confirmed"])
def test_trusted_resolution_methods_are_eligible(
    sku,
    listing_factory,
    resolution_method,
):
    listing_factory(
        price=Decimal("123.45"),
        resolution_method=resolution_method,
        resolution_confidence=Decimal("1.0000"),
    )

    pricepoint = _build(sku)
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("123.4500")


@pytest.mark.parametrize(
    "overrides",
    [
        {"price": None},
        {"condition": None},
        {"observed_at": None},
        {"price_kind": None},
        {"price_kind": "realised", "trade_side": "buy"},
        {
            "listing_sku": None,
            "resolution_method": "unresolved",
            "resolution_confidence": Decimal("0.0000"),
        },
        {
            "resolution_method": "fuzzy_match",
            "resolution_confidence": Decimal("1.0000"),
        },
        {
            "resolution_method": "exact_alias",
            "resolution_confidence": Decimal("0.9999"),
        },
    ],
)
def test_ineligible_listing_facts_are_excluded(sku, listing_factory, overrides):
    listing_factory(**overrides)
    assert _build(sku) is None


def test_reviewed_unresolved_listing_is_excluded(sku, listing_factory):
    listing_factory(
        listing_sku=None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
        reviewed_unresolved_at=timezone.now(),
    )
    assert _build(sku) is None


@pytest.mark.parametrize("source_name", ["personal_records", "unapproved_synthetic"])
def test_source_name_is_not_an_eligibility_allowlist(
    sku,
    listing_factory,
    source_name,
):
    listing_factory(
        price=Decimal("321.00"),
        source_name=source_name,
        price_kind="asking",
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )

    pricepoint = _build(sku)
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("321.0000")


def test_repeated_looking_observations_each_count_once(sku, listing_factory):
    listing_factory(price=Decimal("100.00"), raw_title="Same title")
    listing_factory(price=Decimal("100.00"), raw_title="Same title")

    pricepoint = _build(sku)
    assert pricepoint.n_listings == 2
    assert pricepoint.median == Decimal("100.0000")


def test_population_is_scoped_to_requested_sku_and_condition(sku, listing_factory):
    from catalogue.models import Sku

    other_sku = Sku.objects.create(
        brand="Synthetic",
        model="Other TASK 020 GPU",
        variant="",
        category="gpu",
        launch_msrp=Decimal("24995.00"),
        launch_date=date(2026, 1, 2),
    )
    listing_factory(price=Decimal("100.00"))
    listing_factory(price=Decimal("10.00"), condition="new")
    listing_factory(price=Decimal("20.00"), listing_sku=other_sku)

    pricepoint = _build(sku, condition="used")
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("100.0000")


# --- Manila-day window -----------------------------------------------------


def test_d_minus_90_is_included(sku, listing_factory):
    listing_factory(
        price=Decimal("90.00"),
        observed_at=_manila_instant(AS_OF_DAY - timedelta(days=90), hour=0),
    )
    pricepoint = _build(sku)
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("90.0000")


def test_d_minus_91_is_excluded(sku, listing_factory):
    listing_factory(
        observed_at=_manila_instant(AS_OF_DAY - timedelta(days=91), hour=23, minute=59),
    )
    assert _build(sku) is None


def test_as_of_day_is_excluded(sku, listing_factory):
    listing_factory(
        observed_at=_manila_instant(AS_OF_DAY, hour=0),
    )
    assert _build(sku) is None


def test_utc_instants_are_filtered_by_manila_midnight(sku, listing_factory):
    upper_bound_utc = _manila_instant(AS_OF_DAY, hour=0)
    assert upper_bound_utc == datetime(2026, 8, 8, 16, 0, tzinfo=dt_timezone.utc)

    listing_factory(
        price=Decimal("111.00"),
        observed_at=upper_bound_utc - timedelta(microseconds=1),
    )
    listing_factory(
        price=Decimal("999.00"),
        observed_at=upper_bound_utc,
    )

    pricepoint = _build(sku)
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("111.0000")


def test_same_day_observation_cannot_affect_its_own_baseline(sku, listing_factory):
    listing_factory(
        price=Decimal("100.00"),
        observed_at=_manila_instant(AS_OF_DAY - timedelta(days=1)),
    )
    listing_factory(
        price=Decimal("1.00"),
        observed_at=_manila_instant(AS_OF_DAY),
    )

    pricepoint = _build(sku)
    assert pricepoint.n_listings == 1
    assert pricepoint.median == Decimal("100.0000")


# --- Exact Type 7 and raw MAD ---------------------------------------------


@pytest.mark.parametrize(
    ("prices", "expected_median"),
    [
        (["1.00", "2.00", "9.00"], Decimal("2.0000")),
        (["1.00", "2.00", "3.00", "10.00"], Decimal("2.5000")),
    ],
)
def test_type7_median_for_odd_and_even_populations(
    sku,
    listing_factory,
    prices,
    expected_median,
):
    _create_prices(listing_factory, prices)
    assert _build(sku).median == expected_median


def test_type7_quartiles_use_linear_interpolation(sku, listing_factory):
    _create_prices(listing_factory, ["0.00", "10.00", "20.00", "100.00"])
    pricepoint = _build(sku)
    assert pricepoint.p25 == Decimal("7.5000")
    assert pricepoint.median == Decimal("15.0000")
    assert pricepoint.p75 == Decimal("40.0000")


def test_single_observation_sets_all_quantiles_to_the_price(sku, listing_factory):
    listing_factory(price=Decimal("15500.25"))
    pricepoint = _build(sku)
    assert pricepoint.p25 == Decimal("15500.2500")
    assert pricepoint.median == Decimal("15500.2500")
    assert pricepoint.p75 == Decimal("15500.2500")
    assert pricepoint.mad == Decimal("0.0000")


def test_mad_is_raw_unscaled_median_absolute_deviation(sku, listing_factory):
    _create_prices(listing_factory, ["10.00", "11.00", "100.00"])
    pricepoint = _build(sku)
    assert pricepoint.median == Decimal("11.0000")
    assert pricepoint.mad == Decimal("1.0000")
    assert pricepoint.mad != Decimal("1.4826")


def test_explicit_decimal_context_ignores_process_global_settings(sku, listing_factory):
    _create_prices(
        listing_factory,
        ["9999999999.96", "9999999999.97", "9999999999.98", "9999999999.99"],
    )

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        pricepoint = _build(sku)

    assert pricepoint.p25 == Decimal("9999999999.9675")
    assert pricepoint.median == Decimal("9999999999.9750")
    assert pricepoint.p75 == Decimal("9999999999.9825")
    assert pricepoint.mad == Decimal("0.0100")
    assert all(
        value.as_tuple().exponent == -4
        for value in (
            pricepoint.p25,
            pricepoint.median,
            pricepoint.p75,
            pricepoint.mad,
        )
    )


def test_service_uses_half_even_decimal_and_contains_no_float_path():
    import pricing.baselines as baselines

    source = getsource(baselines)
    assert "ROUND_HALF_EVEN" in source
    assert re.search(r"\bfloat\s*\(", source) is None
    assert "FloatField" not in source


# --- Persistence, auditability, and idempotency ---------------------------


def test_zero_eligible_observations_creates_no_pricepoint(sku):
    from pricing.models import PricePoint

    assert _build(sku) is None
    assert PricePoint.objects.count() == 0


@pytest.mark.parametrize("sample_size", [1, 2, 3, 4])
def test_small_samples_still_create_truthful_snapshots(
    sku,
    listing_factory,
    sample_size,
):
    for number in range(sample_size):
        listing_factory(price=Decimal("100.00") + Decimal(number))

    pricepoint = _build(sku)
    assert pricepoint is not None
    assert pricepoint.n_listings == sample_size


def test_zero_mad_still_creates_a_snapshot(sku, listing_factory):
    _create_prices(listing_factory, ["500.00", "500.00", "500.00", "500.00", "500.00"])
    pricepoint = _build(sku)
    assert pricepoint.n_listings == 5
    assert pricepoint.mad == Decimal("0.0000")


def test_new_snapshot_has_complete_truthful_audit_metadata(sku, listing_factory):
    from pricing.models import PricePoint

    listing_factory(price=Decimal("250.00"))
    before = timezone.now()
    pricepoint = _build(sku)
    after = timezone.now()
    pricepoint.refresh_from_db()

    assert PricePoint.objects.count() == 1
    assert pricepoint.sku_id == sku.pk
    assert pricepoint.condition == "used"
    assert pricepoint.day == AS_OF_DAY
    assert pricepoint.n_listings == 1
    assert pricepoint.window_start_day == AS_OF_DAY - timedelta(days=90)
    assert pricepoint.window_end_day == AS_OF_DAY
    assert before <= pricepoint.calculated_at <= after
    assert timezone.is_aware(pricepoint.calculated_at)
    assert pricepoint.calculation_contract_version == CONTRACT_VERSION
    assert all(
        getattr(pricepoint, field_name) is not None
        for field_name in (
            "mad",
            "window_start_day",
            "window_end_day",
            "calculated_at",
            "calculation_contract_version",
        )
    )


def test_rerun_reuses_same_snapshot_without_any_mutation(sku, listing_factory):
    listing_factory(price=Decimal("100.00"))
    first = _build(sku)
    first_state = model_to_dict(first)
    first_calculated_at = first.calculated_at

    second = _build(sku)
    second.refresh_from_db()

    assert second.pk == first.pk
    assert model_to_dict(second) == first_state
    assert second.calculated_at == first_calculated_at


def test_later_eligible_data_does_not_rewrite_sealed_same_day_snapshot(
    sku,
    listing_factory,
):
    listing_factory(price=Decimal("100.00"))
    first = _build(sku)
    first_state = model_to_dict(first)

    listing_factory(price=Decimal("1000.00"))
    second = _build(sku)
    second.refresh_from_db()

    assert second.pk == first.pk
    assert model_to_dict(second) == first_state
    assert second.n_listings == 1
    assert second.median == Decimal("100.0000")


def test_existing_legacy_snapshot_is_reused_without_recalculation(sku, listing_factory):
    from pricing.models import PricePoint

    legacy = PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=AS_OF_DAY,
        median=Decimal("777.0000"),
        p25=Decimal("700.0000"),
        p75=Decimal("800.0000"),
        n_listings=3,
    )
    listing_factory(price=Decimal("100.00"))

    returned = _build(sku)
    returned.refresh_from_db()
    assert returned.pk == legacy.pk
    assert returned.median == Decimal("777.0000")
    assert returned.mad is None
    assert returned.calculation_contract_version is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_builds_converge_on_one_snapshot(sku, listing_factory):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    listing_factory(price=Decimal("123.00"))
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            thread_sku = Sku.objects.get(pk=sku.pk)
            barrier.wait(timeout=10)
            return _build(thread_sku).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        identifiers = list(executor.map(lambda _number: worker(), range(2)))

    assert identifiers[0] == identifiers[1]
    assert PricePoint.objects.filter(
        sku=sku,
        condition="used",
        day=AS_OF_DAY,
    ).count() == 1


def test_unexpected_insert_failure_leaves_no_partial_pricepoint(
    sku,
    listing_factory,
    monkeypatch,
):
    from pricing.models import PricePoint

    listing_factory(price=Decimal("100.00"))

    def fail_before_insert(self, *args, **kwargs):
        raise RuntimeError("synthetic insert failure")

    monkeypatch.setattr(PricePoint, "save", fail_before_insert)
    with pytest.raises(RuntimeError, match="synthetic insert failure"):
        _build(sku)

    assert PricePoint.objects.count() == 0


# --- Component boundaries -------------------------------------------------


def test_snapshot_build_mutates_no_input_or_downstream_state(sku, listing_factory):
    from catalogue.models import SkuAlias
    from outcomes.models import Outcome
    from pricing.models import DealFlag

    listing = listing_factory(price=Decimal("456.00"))
    raw_listing = listing.raw_listing
    source = raw_listing.source
    listing_before = model_to_dict(listing)
    raw_before = model_to_dict(raw_listing)
    source_before = model_to_dict(source)
    sku_before = model_to_dict(sku)
    alias_count_before = SkuAlias.objects.count()

    pricepoint = _build(sku)

    listing.refresh_from_db()
    raw_listing.refresh_from_db()
    source.refresh_from_db()
    sku.refresh_from_db()
    assert pricepoint is not None
    assert model_to_dict(listing) == listing_before
    assert model_to_dict(raw_listing) == raw_before
    assert model_to_dict(source) == source_before
    assert model_to_dict(sku) == sku_before
    assert SkuAlias.objects.count() == alias_count_before
    assert DealFlag.objects.count() == 0
    assert Outcome.objects.count() == 0


def test_eligibility_query_does_not_read_rawlisting_or_source(
    sku,
    listing_factory,
):
    listing_factory(price=Decimal("456.00"))

    with CaptureQueriesContext(connection) as queries:
        pricepoint = _build(sku)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert pricepoint is not None
    assert "ingestion_rawlisting" not in executed_sql
    assert "sources_source" not in executed_sql
