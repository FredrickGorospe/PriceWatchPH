"""Frozen TASK_021 deterministic DealFlag scoring acceptance tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Context, Decimal, ROUND_UP, localcontext
from inspect import getsource
from itertools import count
import re
from types import SimpleNamespace
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError, close_old_connections, connection
from django.forms.models import model_to_dict
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone


LISTING_DAY = date(2026, 8, 9)
MANILA = ZoneInfo("Asia/Manila")
BASELINE_CONTRACT_VERSION = "asking_price_baseline_v1"
SCORING_REASON = "asking_price_mad_v1"
_UNSET = object()


def _manila_instant(day, *, hour=12, minute=0, second=0):
    return datetime.combine(
        day,
        time(hour, minute, second),
        tzinfo=MANILA,
    ).astimezone(dt_timezone.utc)


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    sequence = count(1)

    def make(*, model=None):
        number = next(sequence)
        return Sku.objects.create(
            brand="Synthetic",
            model=model or f"TASK 021 GPU {number}",
            variant="",
            category="gpu",
            launch_msrp=Decimal("34995.00"),
            launch_date=date(2026, 1, 1),
        )

    return make


@pytest.fixture
def sku(sku_factory):
    return sku_factory(model="TASK 021 primary GPU")


@pytest.fixture
def source_factory(db):
    from sources.models import Source

    def make(name="task_021_source"):
        source, _ = Source.objects.get_or_create(
            name=name,
            defaults={
                "base_url": f"https://{name}.example.invalid",
                "terms_notes": "Synthetic TASK_021 fixture",
                "rate_limit": None,
            },
        )
        return source

    return make


@pytest.fixture
def listing_factory(db, sku, source_factory):
    from ingestion.models import RawListing
    from listings.models import Listing

    sequence = count(1)

    def make(
        *,
        price=Decimal("70.00"),
        condition="used",
        observed_at=_UNSET,
        price_kind="asking",
        trade_side=None,
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
        listing_sku=_UNSET,
        reviewed_unresolved_at=None,
        source_name="task_021_source",
    ):
        number = next(sequence)
        source = source_factory(source_name)
        if observed_at is _UNSET:
            observed_at = _manila_instant(LISTING_DAY)
        selected_sku = sku if listing_sku is _UNSET else listing_sku
        raw_listing = RawListing.objects.create(
            source=source,
            raw_title=f"Synthetic TASK_021 listing {number}",
            raw_price_text="untrusted source price text",
            raw_price=price,
            url=f"https://example.invalid/task-021/{number}",
            seller="seller_anon_token",
            fetched_at=_manila_instant(LISTING_DAY, hour=18),
            external_id=f"task-021-{number}",
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
            reviewed_unresolved_at=reviewed_unresolved_at,
            observed_at=observed_at,
            price_kind=price_kind,
            trade_side=trade_side,
        )

    return make


@pytest.fixture
def pricepoint_factory(db, sku):
    from pricing.models import PricePoint

    def make(
        *,
        point_sku=_UNSET,
        condition="used",
        day=LISTING_DAY,
        median=Decimal("100.0000"),
        p25=_UNSET,
        p75=_UNSET,
        n_listings=5,
        mad=Decimal("10.0000"),
        calculation_contract_version=BASELINE_CONTRACT_VERSION,
        legacy=False,
    ):
        selected_sku = sku if point_sku is _UNSET else point_sku
        fields = {
            "sku": selected_sku,
            "condition": condition,
            "day": day,
            "median": median,
            "p25": median if p25 is _UNSET else p25,
            "p75": median if p75 is _UNSET else p75,
            "n_listings": n_listings,
        }
        if not legacy:
            fields.update(
                mad=mad,
                window_start_day=day - timedelta(days=90),
                window_end_day=day,
                calculated_at=timezone.now(),
                calculation_contract_version=calculation_contract_version,
            )
        return PricePoint.objects.create(**fields)

    return make


def _score(listing):
    from pricing.scoring import score_listing

    return score_listing(listing=listing)


def _confirm_listing(listing, sku):
    from listings.admin import ListingAdmin
    from listings.models import Listing

    listing.sku = sku
    form = SimpleNamespace(cleaned_data={"create_alias": False})
    request = RequestFactory().post("/")
    ListingAdmin(Listing, AdminSite()).save_model(
        request,
        listing,
        form,
        change=True,
    )
    listing.refresh_from_db()


# --- Listing scoring prerequisites ---------------------------------------


@pytest.mark.parametrize("resolution_method", ["exact_alias", "human_confirmed"])
def test_trusted_resolution_methods_can_score(
    listing_factory,
    pricepoint_factory,
    resolution_method,
):
    listing = listing_factory(resolution_method=resolution_method)
    pricepoint_factory()

    flag = _score(listing)

    assert flag is not None
    assert flag.listing_id == listing.pk


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "listing_sku": None,
            "resolution_method": "unresolved",
            "resolution_confidence": Decimal("0.0000"),
        },
        {
            "listing_sku": None,
            "resolution_method": "unresolved",
            "resolution_confidence": Decimal("0.0000"),
            "reviewed_unresolved_at": datetime(
                2026,
                8,
                10,
                tzinfo=dt_timezone.utc,
            ),
        },
        {
            "resolution_method": "fuzzy_match",
            "resolution_confidence": Decimal("1.0000"),
        },
        {"price_kind": "realised", "trade_side": "buy"},
        {"price_kind": None},
        {"listing_sku": None},
        {"condition": None},
        {"price": None},
        {"observed_at": None},
        {"resolution_confidence": Decimal("0.9999")},
    ],
    ids=[
        "unresolved",
        "reviewed-unresolved",
        "fuzzy-match",
        "realised-price",
        "null-price-kind",
        "missing-sku",
        "missing-condition",
        "missing-price",
        "missing-observed-at",
        "inconsistent-confidence",
    ],
)
def test_ineligible_listing_facts_create_no_flag(
    listing_factory,
    pricepoint_factory,
    overrides,
):
    from pricing.models import DealFlag

    listing = listing_factory(**overrides)
    pricepoint_factory()

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


@pytest.mark.parametrize("source_name", ["personal_records", "unapproved_synthetic"])
def test_source_name_does_not_allow_or_deny_scoring(
    listing_factory,
    pricepoint_factory,
    source_name,
):
    listing = listing_factory(
        source_name=source_name,
        price_kind="asking",
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    )
    pricepoint_factory()

    assert _score(listing) is not None


# --- Original Manila day and exact PricePoint identity -------------------


def test_exact_original_day_pricepoint_is_used_instead_of_neighboring_days(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory()
    pricepoint_factory(
        day=LISTING_DAY - timedelta(days=1),
        median=Decimal("70.0000"),
    )
    own_day = pricepoint_factory(day=LISTING_DAY)
    pricepoint_factory(
        day=LISTING_DAY + timedelta(days=1),
        median=Decimal("70.0000"),
    )

    flag = _score(listing)

    assert flag is not None
    assert flag.baseline_pricepoint_id == own_day.pk


def test_later_pricepoint_is_not_a_substitute_for_original_day(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory(day=LISTING_DAY + timedelta(days=1))

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


def test_earlier_pricepoint_is_not_a_substitute_for_original_day(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory(day=LISTING_DAY - timedelta(days=1))

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


@pytest.mark.parametrize("mismatch", ["sku", "condition"])
def test_mismatched_pricepoint_identity_is_not_used(
    listing_factory,
    pricepoint_factory,
    sku_factory,
    mismatch,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    if mismatch == "sku":
        pricepoint_factory(point_sku=sku_factory())
    else:
        pricepoint_factory(condition="new")

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


@pytest.mark.parametrize(
    ("observed_at", "expected_day"),
    [
        (
            datetime(2026, 8, 8, 15, 59, 59, tzinfo=dt_timezone.utc),
            date(2026, 8, 8),
        ),
        (
            datetime(2026, 8, 8, 16, 0, 0, tzinfo=dt_timezone.utc),
            date(2026, 8, 9),
        ),
    ],
)
def test_utc_instants_select_pricepoints_by_manila_day(
    listing_factory,
    pricepoint_factory,
    observed_at,
    expected_day,
):
    listing = listing_factory(observed_at=observed_at)
    selected = pricepoint_factory(day=expected_day)

    flag = _score(listing)

    assert flag is not None
    assert flag.baseline_pricepoint_id == selected.pk


# --- PricePoint usability -------------------------------------------------


@pytest.mark.parametrize("sample_size", [0, 1, 4])
def test_pricepoints_below_five_observations_are_unusable(
    listing_factory,
    pricepoint_factory,
    sample_size,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory(n_listings=sample_size)

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


def test_five_observations_may_produce_a_flag(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory()
    pricepoint_factory(n_listings=5)

    assert _score(listing) is not None


def test_zero_mad_pricepoint_is_unusable_and_unchanged(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint = pricepoint_factory(mad=Decimal("0.0000"))
    before = model_to_dict(pricepoint)

    assert _score(listing) is None
    pricepoint.refresh_from_db()
    assert model_to_dict(pricepoint) == before
    assert DealFlag.objects.count() == 0


def test_legacy_all_null_audit_pricepoint_is_unusable(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    legacy = pricepoint_factory(legacy=True)

    assert _score(listing) is None
    legacy.refresh_from_db()
    assert legacy.mad is None
    assert legacy.window_start_day is None
    assert legacy.window_end_day is None
    assert legacy.calculated_at is None
    assert legacy.calculation_contract_version is None
    assert DealFlag.objects.count() == 0


def test_unrecognized_calculation_contract_is_unusable(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory(calculation_contract_version="future_or_unknown_contract")

    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


# --- Deterministic persisted-evidence score ------------------------------


def test_score_uses_persisted_listing_median_and_raw_mad(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory(price=Decimal("25.00"))
    pricepoint = pricepoint_factory(
        median=Decimal("100.0000"),
        mad=Decimal("25.0000"),
    )

    flag = _score(listing)

    assert flag.score == Decimal("-3.0000")
    assert flag.baseline_pricepoint_id == pricepoint.pk


@pytest.mark.parametrize(
    ("listing_price", "expected_score", "qualifies"),
    [
        (Decimal("700.00"), Decimal("-3.0000"), True),
        (Decimal("699.99"), Decimal("-3.0001"), True),
        (Decimal("700.01"), Decimal("-2.9999"), False),
    ],
)
def test_inclusive_threshold_uses_the_final_four_place_score(
    listing_factory,
    pricepoint_factory,
    listing_price,
    expected_score,
    qualifies,
):
    from pricing.models import DealFlag

    listing = listing_factory(price=listing_price)
    pricepoint_factory(
        median=Decimal("1000.0000"),
        mad=Decimal("100.0000"),
    )

    flag = _score(listing)

    if qualifies:
        assert flag is not None
        assert flag.score == expected_score
    else:
        assert flag is None
        assert DealFlag.objects.count() == 0


@pytest.mark.parametrize(
    ("median", "expected_score", "qualifies"),
    [
        (Decimal("999.9950"), Decimal("-3.0000"), True),
        (Decimal("999.9850"), Decimal("-2.9998"), False),
    ],
)
def test_half_even_rounding_is_behavioral_at_the_threshold(
    listing_factory,
    pricepoint_factory,
    median,
    expected_score,
    qualifies,
):
    listing = listing_factory(price=Decimal("700.00"))
    pricepoint_factory(median=median, mad=Decimal("100.0000"))

    flag = _score(listing)

    if qualifies:
        assert flag is not None
        assert flag.score == expected_score
    else:
        assert flag is None


def test_explicit_decimal_context_ignores_process_global_settings(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory(price=Decimal("9999999999.96"))
    pricepoint_factory(
        median=Decimal("9999999999.9900"),
        p25=Decimal("9999999999.9500"),
        p75=Decimal("9999999999.9900"),
        mad=Decimal("0.0100"),
    )

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        flag = _score(listing)

    assert flag.score == Decimal("-3.0000")


def test_service_contains_no_float_calculation_path():
    import pricing.scoring as scoring

    source = getsource(scoring)
    assert "ROUND_HALF_EVEN" in source
    assert re.search(r"\bfloat\s*\(", source) is None
    assert "FloatField" not in source


def test_supported_extreme_negative_score_is_not_clipped(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory(price=Decimal("0.00"))
    pricepoint_factory(
        median=Decimal("9999999999.9900"),
        p25=Decimal("9999999999.9900"),
        p75=Decimal("9999999999.9900"),
        mad=Decimal("0.0001"),
    )

    flag = _score(listing)

    assert flag.score == Decimal("-99999999999900.0000")


# --- Persistence and sealed idempotency ----------------------------------


def test_qualifying_listing_creates_one_complete_truthful_dealflag(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint = pricepoint_factory()
    before = timezone.now()

    flag = _score(listing)

    after = timezone.now()
    flag.refresh_from_db()
    assert DealFlag.objects.count() == 1
    assert flag.listing_id == listing.pk
    assert flag.baseline_pricepoint_id == pricepoint.pk
    assert flag.score == Decimal("-3.0000")
    assert flag.reason == SCORING_REASON
    assert before <= flag.flagged_at <= after
    assert timezone.is_aware(flag.flagged_at)


def test_nonqualifying_reruns_remain_row_free(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory(price=Decimal("80.00"))
    pricepoint_factory()

    assert _score(listing) is None
    assert _score(listing) is None
    assert DealFlag.objects.count() == 0


def test_qualifying_rerun_returns_same_flag_without_mutation(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory()
    first = _score(listing)
    first_state = model_to_dict(first)

    second = _score(listing)
    second.refresh_from_db()

    assert DealFlag.objects.count() == 1
    assert second.pk == first.pk
    assert model_to_dict(second) == first_state


def test_existing_historical_flag_is_returned_before_recalculation(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory(
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.5000"),
    )
    legacy_pricepoint = pricepoint_factory(legacy=True)
    historical = DealFlag.objects.create(
        listing=listing,
        score=Decimal("-1.2345"),
        baseline_pricepoint=legacy_pricepoint,
        reason="historical prose reason",
        flagged_at=datetime(2025, 1, 1, tzinfo=dt_timezone.utc),
    )
    before = model_to_dict(historical)

    returned = _score(listing)
    returned.refresh_from_db()

    assert returned.pk == historical.pk
    assert model_to_dict(returned) == before


def test_later_pricepoint_cannot_create_a_second_flag(
    listing_factory,
    pricepoint_factory,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    original_day = pricepoint_factory()
    first = _score(listing)
    first_state = model_to_dict(first)
    pricepoint_factory(
        day=LISTING_DAY + timedelta(days=1),
        median=Decimal("1000.0000"),
    )

    returned = _score(listing)
    returned.refresh_from_db()

    assert DealFlag.objects.count() == 1
    assert returned.pk == first.pk
    assert returned.baseline_pricepoint_id == original_day.pk
    assert model_to_dict(returned) == first_state


# --- Approved later SKU resolution ---------------------------------------


def test_approved_later_resolution_uses_existing_original_day_pricepoint(
    sku,
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory(
        listing_sku=None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
        reviewed_unresolved_at=timezone.now(),
    )
    original_day_pricepoint = pricepoint_factory()
    preserved = {
        field: getattr(listing, field)
        for field in (
            "raw_listing_id",
            "price",
            "condition",
            "observed_at",
            "price_kind",
        )
    }

    assert _score(listing) is None
    _confirm_listing(listing, sku)
    flag = _score(listing)

    assert listing.resolution_method == "human_confirmed"
    assert listing.resolution_confidence == Decimal("1.0000")
    assert listing.reviewed_unresolved_at is None
    assert flag.baseline_pricepoint_id == original_day_pricepoint.pk
    for field, value in preserved.items():
        assert getattr(listing, field) == value


def test_later_resolution_without_original_day_pricepoint_builds_nothing(
    sku,
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    import pricing.baselines as baselines
    from pricing.models import DealFlag, PricePoint

    listing = listing_factory(
        listing_sku=None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
    )
    later = pricepoint_factory(day=LISTING_DAY + timedelta(days=1))
    _confirm_listing(listing, sku)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("TASK_021 must not build a historical PricePoint")

    monkeypatch.setattr(baselines, "build_pricepoint", fail_if_called)
    assert _score(listing) is None
    assert DealFlag.objects.count() == 0
    assert list(PricePoint.objects.values_list("pk", flat=True)) == [later.pk]


# --- Concurrency and failure atomicity -----------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_qualification_converges_through_database_uniqueness(
    sku,
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    from listings.models import Listing
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory()
    insert_barrier = Barrier(2)
    original_save = DealFlag.save

    def synchronized_save(self, *args, **kwargs):
        if self._state.adding:
            insert_barrier.wait(timeout=10)
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(DealFlag, "save", synchronized_save)

    def worker():
        close_old_connections()
        try:
            thread_listing = Listing.objects.get(pk=listing.pk)
            return _score(thread_listing).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        identifiers = list(executor.map(lambda _number: worker(), range(2)))

    assert identifiers[0] == identifiers[1]
    assert DealFlag.objects.filter(listing=listing).count() == 1


def test_unexpected_insert_failure_propagates_without_partial_state(
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory()

    def fail_before_insert(self, *args, **kwargs):
        raise RuntimeError("synthetic DealFlag insert failure")

    monkeypatch.setattr(DealFlag, "save", fail_before_insert)
    with pytest.raises(RuntimeError, match="synthetic DealFlag insert failure"):
        _score(listing)

    assert DealFlag.objects.count() == 0


def test_nonidentity_integrity_error_is_not_swallowed(
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    from pricing.models import DealFlag

    listing = listing_factory()
    pricepoint_factory()

    def fail_with_unrelated_integrity_error(self, *args, **kwargs):
        raise IntegrityError("synthetic unrelated database constraint")

    monkeypatch.setattr(DealFlag, "save", fail_with_unrelated_integrity_error)
    with pytest.raises(IntegrityError, match="synthetic unrelated database constraint"):
        _score(listing)

    assert DealFlag.objects.count() == 0


# --- Component boundaries ------------------------------------------------


def test_scoring_never_builds_an_absent_pricepoint(
    listing_factory,
    monkeypatch,
):
    import pricing.baselines as baselines
    import pricing.scoring as scoring
    from pricing.models import DealFlag, PricePoint

    listing = listing_factory()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("TASK_021 must consume, not build, PricePoints")

    monkeypatch.setattr(baselines, "build_pricepoint", fail_if_called)
    if hasattr(scoring, "build_pricepoint"):
        monkeypatch.setattr(scoring, "build_pricepoint", fail_if_called)

    assert scoring.score_listing(listing=listing) is None
    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0


def test_scoring_mutates_no_input_or_outcome_state(
    sku,
    listing_factory,
    pricepoint_factory,
):
    from catalogue.models import SkuAlias
    from outcomes.models import Outcome
    from pricing.models import DealFlag

    listing = listing_factory()
    raw_listing = listing.raw_listing
    source = raw_listing.source
    pricepoint = pricepoint_factory()
    listing_before = model_to_dict(listing)
    raw_before = model_to_dict(raw_listing)
    source_before = model_to_dict(source)
    sku_before = model_to_dict(sku)
    pricepoint_before = model_to_dict(pricepoint)
    alias_count_before = SkuAlias.objects.count()

    flag = _score(listing)

    listing.refresh_from_db()
    raw_listing.refresh_from_db()
    source.refresh_from_db()
    sku.refresh_from_db()
    pricepoint.refresh_from_db()
    assert flag is not None
    assert model_to_dict(listing) == listing_before
    assert model_to_dict(raw_listing) == raw_before
    assert model_to_dict(source) == source_before
    assert model_to_dict(sku) == sku_before
    assert model_to_dict(pricepoint) == pricepoint_before
    assert SkuAlias.objects.count() == alias_count_before
    assert DealFlag.objects.count() == 1
    assert Outcome.objects.count() == 0


def test_scoring_queries_do_not_read_rawlisting_or_source(
    listing_factory,
    pricepoint_factory,
):
    listing = listing_factory()
    pricepoint_factory()

    with CaptureQueriesContext(connection) as queries:
        flag = _score(listing)

    executed_sql = "\n".join(query["sql"].lower() for query in queries)
    assert flag is not None
    assert "ingestion_rawlisting" not in executed_sql
    assert "sources_source" not in executed_sql
