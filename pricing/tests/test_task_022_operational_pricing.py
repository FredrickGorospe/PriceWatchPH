"""Frozen TASK_022 orchestration tests; synthetic data is not market evidence."""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from itertools import count
from zoneinfo import ZoneInfo

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext
from django.utils import timezone


RUN_DAY = date(2026, 8, 9)
MANILA = ZoneInfo("Asia/Manila")
BASELINE_VERSION = "asking_price_baseline_v1"
_UNSET = object()


def _manila_instant(day, *, hour=12, minute=0):
    return datetime.combine(
        day,
        time(hour, minute),
        tzinfo=MANILA,
    ).astimezone(dt_timezone.utc)


def _command_module():
    from pricing.management.commands import price_listings

    return price_listings


def _freeze_current_day(monkeypatch, day=RUN_DAY):
    command_module = _command_module()
    monkeypatch.setattr(command_module, "_current_manila_day", lambda: day)
    return command_module


def _run_command(*arguments):
    stdout = StringIO()
    stderr = StringIO()
    try:
        call_command(
            "price_listings",
            *arguments,
            stdout=stdout,
            stderr=stderr,
            verbosity=0,
        )
    except CommandError as error:
        assert "Unknown command" not in str(error), "price_listings is not implemented"
        raise
    return stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def source_factory(db):
    from sources.models import Source

    sequence = count(1)

    def make(*, name=None, last_successful_fetch=None):
        number = next(sequence)
        return Source.objects.create(
            name=name or f"task_022_source_{number}",
            base_url=f"https://task-022-{number}.example.invalid",
            terms_notes="Synthetic TASK_022 fixture",
            rate_limit=None,
            last_successful_fetch=last_successful_fetch,
        )

    return make


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    sequence = count(1)

    def make(*, model=None):
        number = next(sequence)
        return Sku.objects.create(
            brand="Synthetic",
            model=model or f"TASK 022 GPU {number}",
            variant="",
            category="gpu",
            launch_msrp=Decimal("34995.00"),
            launch_date=date(2026, 1, 1),
        )

    return make


@pytest.fixture
def listing_factory(db, source_factory, sku_factory):
    from ingestion.models import RawListing
    from listings.models import Listing

    sequence = count(1)
    default_sku = sku_factory(model="TASK 022 default GPU")

    def make(
        *,
        listing_sku=_UNSET,
        source=None,
        price=Decimal("70.00"),
        condition="used",
        observed_at=_UNSET,
        resolved_at=_UNSET,
        price_kind="asking",
        resolution_method="exact_alias",
        resolution_confidence=Decimal("1.0000"),
    ):
        number = next(sequence)
        selected_sku = default_sku if listing_sku is _UNSET else listing_sku
        selected_source = source or source_factory()
        selected_observed_at = (
            _manila_instant(RUN_DAY)
            if observed_at is _UNSET
            else observed_at
        )
        selected_resolved_at = (
            _manila_instant(RUN_DAY, hour=13)
            if resolved_at is _UNSET
            else resolved_at
        )
        raw_listing = RawListing.objects.create(
            source=selected_source,
            raw_title=f"Synthetic TASK 022 listing {number}",
            raw_price_text="untrusted source price text",
            raw_price=price,
            url=f"https://example.invalid/task-022/{number}",
            seller="seller_anon_token",
            fetched_at=_manila_instant(RUN_DAY, hour=18),
            external_id=f"task-022-{number}",
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
            resolved_at=selected_resolved_at,
            observed_at=selected_observed_at,
            price_kind=price_kind,
            trade_side="buy" if price_kind == "realised" else None,
        )

    make.default_sku = default_sku
    return make


@pytest.fixture
def pricepoint_factory(db):
    from pricing.models import PricePoint

    def make(
        *,
        sku,
        condition="used",
        day=RUN_DAY,
        median=Decimal("100.0000"),
        mad=Decimal("10.0000"),
        n_listings=5,
    ):
        return PricePoint.objects.create(
            sku=sku,
            condition=condition,
            day=day,
            median=median,
            p25=median,
            p75=median,
            n_listings=n_listings,
            mad=mad,
            window_start_day=day - timedelta(days=90),
            window_end_day=day,
            calculated_at=timezone.now(),
            calculation_contract_version=BASELINE_VERSION,
        )

    return make


def _create_baseline_population(listing_factory, *, sku, resolved_day=None):
    resolved_day = resolved_day or RUN_DAY - timedelta(days=1)
    listings = []
    for price in ("80.00", "90.00", "100.00", "110.00", "120.00"):
        listings.append(
            listing_factory(
                listing_sku=sku,
                price=Decimal(price),
                observed_at=_manila_instant(RUN_DAY - timedelta(days=1)),
                resolved_at=_manila_instant(resolved_day),
            )
        )
    return listings


# --- Command and run-day contract ----------------------------------------


def test_command_is_registered_and_empty_run_has_concise_summary(db, monkeypatch):
    _freeze_current_day(monkeypatch)

    stdout, stderr = _run_command("--day", RUN_DAY.isoformat())

    assert stdout == (
        "Pricing 2026-08-09 complete: "
        "snapshot_identities=0 listings_evaluated=0\n"
    )
    assert stderr == ""


def test_explicit_run_day_is_passed_unchanged_to_baseline_service(
    listing_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    listing = listing_factory(resolved_at=_manila_instant(RUN_DAY - timedelta(days=1)))
    build_calls = []
    monkeypatch.setattr(
        command_module,
        "build_pricepoint",
        lambda **kwargs: build_calls.append(kwargs),
    )
    monkeypatch.setattr(command_module, "score_listing", lambda **_kwargs: None)

    _run_command("--day", "2026-08-09")

    assert build_calls == [
        {
            "sku": listing.sku,
            "condition": "used",
            "as_of_day": RUN_DAY,
        }
    ]


def test_default_run_day_uses_manila_date_not_utc_date(db, monkeypatch):
    command_module = _command_module()
    instant = datetime(2026, 8, 8, 16, 30, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(command_module.timezone, "now", lambda: instant)

    stdout, _stderr = _run_command()

    assert stdout.startswith("Pricing 2026-08-09 complete:")


def test_invalid_explicit_day_fails_clearly(db):
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        _run_command("--day", "09/08/2026")


def test_future_day_fails_before_services_or_writes(db, monkeypatch):
    from pricing.models import DealFlag, PricePoint

    command_module = _freeze_current_day(monkeypatch)

    def fail_if_called(**_kwargs):
        raise AssertionError("future runs must fail before pricing services")

    monkeypatch.setattr(command_module, "build_pricepoint", fail_if_called)
    monkeypatch.setattr(command_module, "score_listing", fail_if_called)

    with pytest.raises(CommandError, match="future"):
        _run_command("--day", (RUN_DAY + timedelta(days=1)).isoformat())

    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0


def test_past_day_replay_scores_but_never_calls_baseline_service(
    listing_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    past_day = RUN_DAY - timedelta(days=1)
    listing = listing_factory(
        observed_at=_manila_instant(past_day),
        resolved_at=_manila_instant(past_day),
    )
    scored = []

    def fail_if_called(**_kwargs):
        raise AssertionError("historical replay must not build PricePoints")

    monkeypatch.setattr(command_module, "build_pricepoint", fail_if_called)
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: scored.append(listing.pk),
    )

    stdout, _stderr = _run_command("--day", past_day.isoformat())

    assert scored == [listing.pk]
    assert "snapshot_identities=0 listings_evaluated=1" in stdout


# --- Selection, delegation, and ordering ---------------------------------


def test_current_day_snapshot_identities_are_distinct_non_null_and_ordered(
    listing_factory,
    sku_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    first_sku = sku_factory(model="Identity A")
    second_sku = sku_factory(model="Identity B")
    listing_factory(listing_sku=second_sku, condition="used")
    listing_factory(listing_sku=first_sku, condition="used")
    listing_factory(listing_sku=second_sku, condition="new")
    listing_factory(listing_sku=first_sku, condition="used")
    listing_factory(
        listing_sku=None,
        condition="used",
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
    )
    listing_factory(listing_sku=first_sku, condition=None)
    identities = []
    monkeypatch.setattr(
        command_module,
        "build_pricepoint",
        lambda *, sku, condition, as_of_day: identities.append(
            (sku.pk, condition, as_of_day)
        ),
    )
    monkeypatch.setattr(command_module, "score_listing", lambda **_kwargs: None)

    _run_command("--day", RUN_DAY.isoformat())

    assert identities == [
        (first_sku.pk, "used", RUN_DAY),
        (second_sku.pk, "new", RUN_DAY),
        (second_sku.pk, "used", RUN_DAY),
    ]


def test_snapshot_identity_requires_observation_on_run_day_not_resolution_only(
    listing_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    historical = listing_factory(
        observed_at=_manila_instant(RUN_DAY - timedelta(days=20)),
        resolved_at=_manila_instant(RUN_DAY),
    )
    built = []
    scored = []
    monkeypatch.setattr(
        command_module,
        "build_pricepoint",
        lambda **kwargs: built.append(kwargs),
    )
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: scored.append(listing.pk),
    )

    _run_command("--day", RUN_DAY.isoformat())

    assert built == []
    assert scored == [historical.pk]


def test_scoring_union_is_deduplicated_bounded_and_primary_key_ordered(
    listing_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    observed_only = listing_factory(
        observed_at=_manila_instant(RUN_DAY),
        resolved_at=_manila_instant(RUN_DAY - timedelta(days=1)),
    )
    resolved_only = listing_factory(
        observed_at=_manila_instant(RUN_DAY - timedelta(days=10)),
        resolved_at=_manila_instant(RUN_DAY),
    )
    both = listing_factory()
    listing_factory(
        observed_at=_manila_instant(RUN_DAY - timedelta(days=10)),
        resolved_at=_manila_instant(RUN_DAY - timedelta(days=1)),
    )
    visited = []
    monkeypatch.setattr(command_module, "build_pricepoint", lambda **_kwargs: None)
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: visited.append(listing.pk),
    )

    _run_command("--day", RUN_DAY.isoformat())

    assert visited == sorted([observed_only.pk, resolved_only.pk, both.pk])
    assert visited.count(both.pk) == 1


def test_all_snapshot_calls_finish_before_any_scoring_call(
    listing_factory,
    sku_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    first_sku = sku_factory(model="Ordering A")
    second_sku = sku_factory(model="Ordering B")
    first_listing = listing_factory(listing_sku=first_sku)
    second_listing = listing_factory(listing_sku=second_sku)
    events = []
    monkeypatch.setattr(
        command_module,
        "build_pricepoint",
        lambda *, sku, condition, as_of_day: events.append(("build", sku.pk)),
    )
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: events.append(("score", listing.pk)),
    )

    _run_command("--day", RUN_DAY.isoformat())

    assert events == [
        ("build", first_sku.pk),
        ("build", second_sku.pk),
        ("score", first_listing.pk),
        ("score", second_listing.pk),
    ]


def test_command_passes_every_temporal_candidate_to_authoritative_scorer(
    listing_factory,
    monkeypatch,
):
    command_module = _freeze_current_day(monkeypatch)
    eligible = listing_factory()
    realised = listing_factory(price_kind="realised")
    unresolved = listing_factory(
        listing_sku=None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
    )
    scored = []
    monkeypatch.setattr(command_module, "build_pricepoint", lambda **_kwargs: None)
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: scored.append(listing.pk),
    )

    _run_command("--day", RUN_DAY.isoformat())

    assert scored == [eligible.pk, realised.pk, unresolved.pk]


def test_operational_selection_queries_neither_rawlisting_nor_source_policy(
    listing_factory,
    source_factory,
    sku_factory,
    monkeypatch,
):
    from sources.models import Source

    command_module = _freeze_current_day(monkeypatch)
    first_source = Source.objects.get(name="personal_records")
    second_source = source_factory(name="unapproved_synthetic")
    first_sku = sku_factory(model="Source neutral A")
    second_sku = sku_factory(model="Source neutral B")
    first = listing_factory(listing_sku=first_sku, source=first_source)
    second = listing_factory(listing_sku=second_sku, source=second_source)
    built = []
    scored = []
    monkeypatch.setattr(
        command_module,
        "build_pricepoint",
        lambda *, sku, **_kwargs: built.append(sku.pk),
    )
    monkeypatch.setattr(
        command_module,
        "score_listing",
        lambda *, listing: scored.append(listing.pk),
    )

    with CaptureQueriesContext(connection) as queries:
        _run_command("--day", RUN_DAY.isoformat())

    sql = "\n".join(query["sql"].lower() for query in queries)
    assert built == [first_sku.pk, second_sku.pk]
    assert scored == [first.pk, second.pk]
    assert "ingestion_rawlisting" not in sql
    assert "sources_source" not in sql


# --- Integrated historical boundary and sealed reruns --------------------


def test_later_resolved_listing_without_original_snapshot_gets_no_backfill(
    listing_factory,
    monkeypatch,
):
    from pricing.models import DealFlag, PricePoint

    _freeze_current_day(monkeypatch)
    original_day = RUN_DAY - timedelta(days=20)
    historical = listing_factory(
        price=Decimal("1.00"),
        observed_at=_manila_instant(original_day),
        resolved_at=_manila_instant(RUN_DAY),
    )
    listing_factory(
        listing_sku=historical.sku,
        price=Decimal("100.00"),
        observed_at=_manila_instant(RUN_DAY),
        resolved_at=_manila_instant(RUN_DAY),
    )

    _run_command("--day", RUN_DAY.isoformat())

    assert list(PricePoint.objects.values_list("day", flat=True)) == [RUN_DAY]
    assert DealFlag.objects.count() == 0


def test_later_resolved_listing_can_use_existing_original_day_snapshot(
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    from pricing.models import DealFlag, PricePoint

    _freeze_current_day(monkeypatch)
    original_day = RUN_DAY - timedelta(days=20)
    listing = listing_factory(
        price=Decimal("70.00"),
        observed_at=_manila_instant(original_day),
        resolved_at=_manila_instant(RUN_DAY),
    )
    original = pricepoint_factory(sku=listing.sku, day=original_day)

    _run_command("--day", RUN_DAY.isoformat())

    flag = DealFlag.objects.get(listing=listing)
    assert flag.baseline_pricepoint_id == original.pk
    assert list(PricePoint.objects.values_list("pk", flat=True)) == [original.pk]


def test_current_day_snapshot_is_built_before_listing_is_scored(
    listing_factory,
    monkeypatch,
):
    from pricing.models import DealFlag, PricePoint

    _freeze_current_day(monkeypatch)
    sku = listing_factory.default_sku
    _create_baseline_population(listing_factory, sku=sku)
    current = listing_factory(
        listing_sku=sku,
        price=Decimal("60.00"),
        observed_at=_manila_instant(RUN_DAY),
        resolved_at=_manila_instant(RUN_DAY),
    )

    _run_command("--day", RUN_DAY.isoformat())

    point = PricePoint.objects.get(sku=sku, condition="used", day=RUN_DAY)
    flag = DealFlag.objects.get(listing=current)
    assert point.n_listings == 5
    assert flag.baseline_pricepoint_id == point.pk


def test_complete_rerun_reuses_one_snapshot_and_one_flag(
    listing_factory,
    monkeypatch,
):
    from pricing.models import DealFlag, PricePoint

    _freeze_current_day(monkeypatch)
    sku = listing_factory.default_sku
    _create_baseline_population(listing_factory, sku=sku)
    current = listing_factory(listing_sku=sku, price=Decimal("60.00"))

    first_stdout, _stderr = _run_command("--day", RUN_DAY.isoformat())
    point = PricePoint.objects.get()
    flag = DealFlag.objects.get(listing=current)
    point_before = model_to_dict(point)
    flag_before = model_to_dict(flag)

    second_stdout, _stderr = _run_command("--day", RUN_DAY.isoformat())

    point.refresh_from_db()
    flag.refresh_from_db()
    assert PricePoint.objects.count() == 1
    assert DealFlag.objects.count() == 1
    assert model_to_dict(point) == point_before
    assert model_to_dict(flag) == flag_before
    assert second_stdout == first_stdout


# --- Whole-run failure, retry, and state boundaries ----------------------


def test_baseline_failure_propagates_rolls_back_prior_write_and_prints_nothing(
    listing_factory,
    sku_factory,
    monkeypatch,
):
    from pricing.models import PricePoint

    command_module = _freeze_current_day(monkeypatch)
    first_sku = sku_factory(model="Failure first")
    second_sku = sku_factory(model="Failure second")
    listing_factory(listing_sku=first_sku)
    listing_factory(listing_sku=second_sku)

    def build_or_fail(*, sku, condition, as_of_day):
        if sku.pk == second_sku.pk:
            raise RuntimeError("synthetic baseline failure")
        return PricePoint.objects.create(
            sku=sku,
            condition=condition,
            day=as_of_day,
            median=Decimal("100.0000"),
            p25=Decimal("100.0000"),
            p75=Decimal("100.0000"),
            n_listings=1,
            mad=Decimal("0.0000"),
            window_start_day=as_of_day - timedelta(days=90),
            window_end_day=as_of_day,
            calculated_at=timezone.now(),
            calculation_contract_version=BASELINE_VERSION,
        )

    monkeypatch.setattr(command_module, "build_pricepoint", build_or_fail)
    monkeypatch.setattr(command_module, "score_listing", lambda **_kwargs: None)
    stdout = StringIO()

    with pytest.raises(RuntimeError, match="synthetic baseline failure"):
        call_command(
            "price_listings",
            "--day",
            RUN_DAY.isoformat(),
            stdout=stdout,
            verbosity=0,
        )

    assert stdout.getvalue() == ""
    assert PricePoint.objects.count() == 0


def test_scoring_failure_rolls_back_all_evidence_then_retry_is_idempotent(
    listing_factory,
    monkeypatch,
):
    from pricing.models import DealFlag, PricePoint
    from pricing.scoring import score_listing as real_score_listing

    command_module = _freeze_current_day(monkeypatch)
    sku = listing_factory.default_sku
    _create_baseline_population(listing_factory, sku=sku)
    first = listing_factory(listing_sku=sku, price=Decimal("60.00"))
    second = listing_factory(listing_sku=sku, price=Decimal("50.00"))

    def score_then_fail(*, listing):
        if listing.pk == second.pk:
            raise RuntimeError("synthetic scoring failure")
        return real_score_listing(listing=listing)

    monkeypatch.setattr(command_module, "score_listing", score_then_fail)
    with pytest.raises(RuntimeError, match="synthetic scoring failure"):
        _run_command("--day", RUN_DAY.isoformat())

    assert PricePoint.objects.count() == 0
    assert DealFlag.objects.count() == 0

    monkeypatch.setattr(command_module, "score_listing", real_score_listing)
    _run_command("--day", RUN_DAY.isoformat())
    _run_command("--day", RUN_DAY.isoformat())

    assert PricePoint.objects.count() == 1
    assert set(DealFlag.objects.values_list("listing_id", flat=True)) == {
        first.pk,
        second.pk,
    }


def test_success_mutates_only_service_owned_pricing_evidence(
    listing_factory,
    source_factory,
    monkeypatch,
):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import RawListing, Swap
    from listings.models import Listing
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    _freeze_current_day(monkeypatch)
    marker = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    source = source_factory(last_successful_fetch=marker)
    sku = listing_factory.default_sku
    history = _create_baseline_population(listing_factory, sku=sku)
    current = listing_factory(
        listing_sku=sku,
        source=source,
        price=Decimal("60.00"),
    )
    raw_before = {
        row.pk: model_to_dict(row)
        for row in RawListing.objects.order_by("pk")
    }
    listing_before = {
        row.pk: model_to_dict(row)
        for row in Listing.objects.order_by("pk")
    }
    sku_before = {row.pk: model_to_dict(row) for row in Sku.objects.order_by("pk")}
    source_before = model_to_dict(source)
    nonpricing_counts = {
        "aliases": SkuAlias.objects.count(),
        "swaps": Swap.objects.count(),
        "outcomes": Outcome.objects.count(),
    }

    _run_command("--day", RUN_DAY.isoformat())

    source.refresh_from_db()
    assert {
        row.pk: model_to_dict(row)
        for row in RawListing.objects.order_by("pk")
    } == raw_before
    assert {
        row.pk: model_to_dict(row)
        for row in Listing.objects.order_by("pk")
    } == listing_before
    assert {row.pk: model_to_dict(row) for row in Sku.objects.order_by("pk")} == sku_before
    assert model_to_dict(source) == source_before
    assert SkuAlias.objects.count() == nonpricing_counts["aliases"]
    assert Swap.objects.count() == nonpricing_counts["swaps"]
    assert Outcome.objects.count() == nonpricing_counts["outcomes"]
    assert source.last_successful_fetch == marker
    assert PricePoint.objects.count() == 1
    assert DealFlag.objects.filter(listing=current).count() == 1
    assert all(not listing.deal_flags.exists() for listing in history)


# --- Admin evidence visibility -------------------------------------------


@pytest.mark.parametrize(
    ("model_name", "expected_display", "expected_filters", "expected_ordering"),
    [
        (
            "pricepoint",
            (
                "sku",
                "condition",
                "day",
                "median",
                "mad",
                "n_listings",
                "window_start_day",
                "window_end_day",
                "calculation_contract_version",
                "calculated_at",
            ),
            ("condition", "day", "calculation_contract_version"),
            ("-day", "sku_id", "condition"),
        ),
        (
            "dealflag",
            ("listing", "score", "baseline_pricepoint", "reason", "flagged_at"),
            ("reason", "flagged_at"),
            ("-flagged_at", "pk"),
        ),
    ],
)
def test_admin_changelists_expose_approved_persisted_evidence(
    model_name,
    expected_display,
    expected_filters,
    expected_ordering,
):
    from pricing.models import DealFlag, PricePoint

    model = PricePoint if model_name == "pricepoint" else DealFlag
    model_admin = admin.site._registry[model]
    assert tuple(model_admin.list_display) == expected_display
    assert tuple(model_admin.list_filter) == expected_filters
    assert tuple(model_admin.ordering) == expected_ordering

    if model_name == "pricepoint":
        assert tuple(model_admin.list_select_related) == ("sku",)
    else:
        assert tuple(model_admin.list_select_related) == (
            "listing",
            "baseline_pricepoint",
            "baseline_pricepoint__sku",
        )


@pytest.mark.parametrize("model_name", ["pricepoint", "dealflag"])
def test_admin_evidence_render_never_invokes_pricing_services(
    model_name,
    admin_client,
    listing_factory,
    pricepoint_factory,
    monkeypatch,
):
    import pricing.baselines as baselines
    import pricing.scoring as scoring
    from pricing.models import DealFlag

    listing = listing_factory()
    point = pricepoint_factory(sku=listing.sku)
    if model_name == "dealflag":
        DealFlag.objects.create(
            listing=listing,
            score=Decimal("-3.0000"),
            baseline_pricepoint=point,
            reason="asking_price_mad_v1",
            flagged_at=timezone.now(),
        )

    def fail_if_called(**_kwargs):
        raise AssertionError("admin must render persisted evidence only")

    monkeypatch.setattr(baselines, "build_pricepoint", fail_if_called)
    monkeypatch.setattr(scoring, "score_listing", fail_if_called)
    response = admin_client.get(f"/admin/pricing/{model_name}/")

    assert response.status_code == 200
