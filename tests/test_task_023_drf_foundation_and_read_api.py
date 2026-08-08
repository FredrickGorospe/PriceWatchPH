import importlib.util
import json
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import Resolver404, resolve, reverse


SKU_FIELDS = {
    "id",
    "brand",
    "model",
    "variant",
    "category",
    "launch_msrp",
    "launch_date",
}
SKU_SUMMARY_FIELDS = {"id", "brand", "model", "variant", "category"}
LISTING_FIELDS = {
    "id",
    "sku_id",
    "price",
    "condition",
    "resolution_confidence",
    "resolution_method",
    "resolved_at",
    "observed_at",
    "price_kind",
    "trade_side",
}
PRICEPOINT_FIELDS = {
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
}
DEALFLAG_FIELDS = {
    "id",
    "sku",
    "listing",
    "baseline_pricepoint",
    "score",
    "reason",
    "flagged_at",
}
PAGINATION_FIELDS = {"count", "next", "previous", "results"}
UTC = dt_timezone.utc


@pytest.fixture
def user_factory(db):
    def make(*, is_staff=True, is_superuser=False):
        return get_user_model().objects.create_user(
            username=f"task023-{uuid4().hex}",
            password="test-password",
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return make


@pytest.fixture
def grant_view_permissions():
    def grant(user, *models):
        permissions = []
        for model in models:
            content_type = ContentType.objects.get_for_model(model)
            permissions.append(
                Permission.objects.get(
                    content_type=content_type,
                    codename=f"view_{model._meta.model_name}",
                )
            )
        user.user_permissions.add(*permissions)

    return grant


@pytest.fixture
def source_factory(db):
    def make(**overrides):
        from sources.models import Source

        values = {
            "name": f"task_023_{uuid4().hex}",
            "base_url": "https://source.example.invalid",
            "terms_notes": "synthetic TASK_023 source",
            "rate_limit": None,
        }
        values.update(overrides)
        return Source.objects.create(**values)

    return make


@pytest.fixture
def sku_factory(db):
    def make(**overrides):
        from catalogue.models import Sku

        marker = uuid4().hex
        values = {
            "brand": f"Brand-{marker}",
            "model": f"Model-{marker}",
            "variant": "",
            "category": "gpu",
            "launch_msrp": Decimal("34995.00"),
            "launch_date": date(2023, 4, 1),
        }
        values.update(overrides)
        return Sku.objects.create(**values)

    return make


@pytest.fixture
def raw_listing_factory(db, source_factory):
    def make(**overrides):
        from ingestion.models import RawListing

        marker = uuid4().hex
        values = {
            "source": source_factory(),
            "raw_title": f"RAW-TITLE-MUST-NOT-LEAK-{marker}",
            "raw_price_text": f"RAW-PRICE-MUST-NOT-LEAK-{marker}",
            "raw_price": Decimal("15500.00"),
            "url": f"https://raw.example.invalid/MUST-NOT-LEAK/{marker}",
            "seller": f"SELLER-MUST-NOT-LEAK-{marker}",
            "fetched_at": datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
            "occurred_at": datetime(2026, 8, 8, 1, 2, 3, tzinfo=UTC),
            "external_id": f"RAW-ID-MUST-NOT-LEAK-{marker}",
            "payload": {"must_not_leak": marker},
        }
        values.update(overrides)
        return RawListing.objects.create(**values)

    return make


@pytest.fixture
def listing_factory(db, raw_listing_factory, sku_factory):
    sentinel = object()

    def make(*, raw_listing=sentinel, sku=sentinel, **overrides):
        from listings.models import Listing

        if raw_listing is sentinel:
            raw_listing = raw_listing_factory()
        if sku is sentinel:
            sku = sku_factory()
        values = {
            "raw_listing": raw_listing,
            "sku": sku,
            "price": Decimal("15500.00"),
            "condition": "used",
            "location": "Quezon City",
            "resolution_confidence": Decimal("1.0000"),
            "resolution_method": "exact_alias",
            "resolved_at": datetime(2026, 8, 9, 4, 5, 6, tzinfo=UTC),
            "reviewed_unresolved_at": None,
            "observed_at": datetime(2026, 8, 8, 3, 4, 5, tzinfo=UTC),
            "price_kind": "asking",
            "trade_side": None,
        }
        values.update(overrides)
        return Listing.objects.create(**values)

    return make


@pytest.fixture
def pricepoint_factory(db, sku_factory):
    sentinel = object()

    def make(*, sku=sentinel, **overrides):
        from pricing.models import PricePoint

        if sku is sentinel:
            sku = sku_factory()
        values = {
            "sku": sku,
            "condition": "used",
            "day": date(2026, 8, 8),
            "median": Decimal("20000.0000"),
            "p25": Decimal("19000.0000"),
            "p75": Decimal("21000.0000"),
            "n_listings": 7,
            "mad": Decimal("1500.0000"),
            "window_start_day": date(2026, 5, 10),
            "window_end_day": date(2026, 8, 8),
            "calculated_at": datetime(2026, 8, 8, 16, 30, 0, tzinfo=UTC),
            "calculation_contract_version": "asking_price_baseline_v1",
        }
        values.update(overrides)
        return PricePoint.objects.create(**values)

    return make


@pytest.fixture
def dealflag_factory(db, listing_factory, pricepoint_factory):
    sentinel = object()

    def make(*, listing=sentinel, baseline_pricepoint=sentinel, **overrides):
        from pricing.models import DealFlag

        if listing is sentinel:
            listing = listing_factory()
        if baseline_pricepoint is sentinel:
            baseline_pricepoint = pricepoint_factory(sku=listing.sku)
        values = {
            "listing": listing,
            "baseline_pricepoint": baseline_pricepoint,
            "score": Decimal("-3.2500"),
            "reason": "asking_price_mad_v1",
            "flagged_at": datetime(2026, 8, 9, 5, 6, 7, tzinfo=UTC),
        }
        values.update(overrides)
        return DealFlag.objects.create(**values)

    return make


def _login_with_views(client, user_factory, grant_view_permissions, *models):
    user = user_factory()
    grant_view_permissions(user, *models)
    client.force_login(user)
    return user


def _page(response):
    assert response.status_code == 200
    data = response.json()
    assert set(data) == PAGINATION_FIELDS
    return data


def test_drf_dependency_and_global_api_settings_are_frozen():
    assert importlib.util.find_spec("rest_framework") is not None
    assert "rest_framework" in settings.INSTALLED_APPS
    assert list(settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]) == [
        "rest_framework.authentication.SessionAuthentication"
    ]
    assert list(settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]) == [
        "rest_framework.permissions.IsAuthenticated"
    ]
    assert settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] is True
    assert settings.REST_FRAMEWORK["PAGE_SIZE"] == 25


def test_api_v1_namespace_and_exact_routes_are_stable():
    assert reverse("api-v1:sku-list") == "/api/v1/skus/"
    assert reverse("api-v1:sku-detail", args=[17]) == "/api/v1/skus/17/"
    assert reverse("api-v1:sku-pricepoint-list", args=[17]) == (
        "/api/v1/skus/17/price-points/"
    )
    assert reverse("api-v1:listing-detail", args=[23]) == "/api/v1/listings/23/"
    assert reverse("api-v1:dealflag-list") == "/api/v1/deal-flags/"


def test_anonymous_api_request_is_denied(client):
    response = client.get(reverse("api-v1:sku-list"))

    assert response.status_code == 403


def test_nonstaff_user_is_denied_even_with_view_permission(
    client,
    user_factory,
    grant_view_permissions,
):
    from catalogue.models import Sku

    user = user_factory(is_staff=False)
    grant_view_permissions(user, Sku)
    client.force_login(user)

    assert client.get(reverse("api-v1:sku-list")).status_code == 403


def test_staff_user_without_required_view_permission_is_denied(client, user_factory):
    client.force_login(user_factory())

    assert client.get(reverse("api-v1:sku-list")).status_code == 403


def test_permissions_are_resource_specific(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
    listing_factory,
):
    from catalogue.models import Sku

    sku = sku_factory()
    listing = listing_factory(sku=sku)
    _login_with_views(client, user_factory, grant_view_permissions, Sku)

    assert client.get(reverse("api-v1:sku-list")).status_code == 200
    assert client.get(reverse("api-v1:sku-detail", args=[sku.pk])).status_code == 200
    assert client.get(reverse("api-v1:listing-detail", args=[listing.pk])).status_code == 403


def test_listing_detail_requires_listing_view_permission_only(
    client,
    user_factory,
    grant_view_permissions,
    listing_factory,
):
    from listings.models import Listing

    listing = listing_factory()
    _login_with_views(client, user_factory, grant_view_permissions, Listing)

    assert client.get(reverse("api-v1:listing-detail", args=[listing.pk])).status_code == 200
    assert client.get(reverse("api-v1:sku-list")).status_code == 403


def test_pricepoint_history_requires_sku_and_pricepoint_view_permissions(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    user = user_factory()
    grant_view_permissions(user, PricePoint)
    client.force_login(user)
    url = reverse("api-v1:sku-pricepoint-list", args=[sku.pk])

    assert client.get(url).status_code == 403
    grant_view_permissions(user, Sku)
    assert client.get(url).status_code == 200


def test_deal_feed_requires_every_embedded_resource_view_permission(
    client,
    user_factory,
    grant_view_permissions,
):
    from catalogue.models import Sku
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    user = user_factory()
    grant_view_permissions(user, Sku, Listing, DealFlag)
    client.force_login(user)
    url = reverse("api-v1:dealflag-list")

    assert client.get(url).status_code == 403
    grant_view_permissions(user, PricePoint)
    assert client.get(url).status_code == 200


def test_authorized_missing_detail_returns_404(
    client,
    user_factory,
    grant_view_permissions,
):
    from catalogue.models import Sku
    from listings.models import Listing

    _login_with_views(client, user_factory, grant_view_permissions, Sku, Listing)

    assert client.get(reverse("api-v1:sku-detail", args=[999999])).status_code == 404
    assert client.get(reverse("api-v1:listing-detail", args=[999999])).status_code == 404


def test_sku_representation_has_exact_fields_and_money_string(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
):
    from catalogue.models import Sku

    sku = sku_factory(
        brand="NVIDIA",
        model="RTX 4070",
        variant="Founders Edition",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 13),
    )
    _login_with_views(client, user_factory, grant_view_permissions, Sku)

    data = client.get(reverse("api-v1:sku-detail", args=[sku.pk])).json()

    assert set(data) == SKU_FIELDS
    assert data == {
        "id": sku.pk,
        "brand": "NVIDIA",
        "model": "RTX 4070",
        "variant": "Founders Edition",
        "category": "gpu",
        "launch_msrp": "34995.00",
        "launch_date": "2023-04-13",
    }


def test_listing_representation_is_derived_only_and_preserves_decimal_and_time(
    client,
    user_factory,
    grant_view_permissions,
    raw_listing_factory,
    listing_factory,
):
    from listings.models import Listing

    raw = raw_listing_factory(
        raw_title="RAW-TITLE-023-SECRET",
        raw_price_text="RAW-PRICE-023-SECRET",
        url="https://raw.example.invalid/RAW-URL-023-SECRET",
        seller="RAW-SELLER-023-SECRET",
        payload={"secret": "RAW-PAYLOAD-023-SECRET"},
    )
    listing = listing_factory(
        raw_listing=raw,
        price=Decimal("15500.00"),
        resolution_confidence=Decimal("0.8750"),
        resolved_at=datetime(2026, 8, 9, 4, 5, 6, tzinfo=UTC),
        observed_at=datetime(2026, 8, 8, 3, 4, 5, tzinfo=UTC),
    )
    _login_with_views(client, user_factory, grant_view_permissions, Listing)

    response = client.get(reverse("api-v1:listing-detail", args=[listing.pk]))
    assert response.status_code == 200
    data = response.json()

    assert set(data) == LISTING_FIELDS
    assert data["sku_id"] == listing.sku_id
    assert data["price"] == "15500.00"
    assert data["resolution_confidence"] == "0.8750"
    assert data["resolved_at"] == "2026-08-09T04:05:06Z"
    assert data["observed_at"] == "2026-08-08T03:04:05Z"
    encoded = json.dumps(data)
    for marker in (
        "RAW-TITLE-023-SECRET",
        "RAW-PRICE-023-SECRET",
        "RAW-URL-023-SECRET",
        "RAW-SELLER-023-SECRET",
        "RAW-PAYLOAD-023-SECRET",
    ):
        assert marker not in encoded


def test_nullable_listing_facts_remain_null(
    client,
    user_factory,
    grant_view_permissions,
    listing_factory,
):
    from listings.models import Listing

    listing = listing_factory(
        sku=None,
        price=None,
        condition=None,
        observed_at=None,
        price_kind=None,
        trade_side=None,
        resolution_method="unresolved",
        resolution_confidence=Decimal("0.0000"),
    )
    _login_with_views(client, user_factory, grant_view_permissions, Listing)

    data = client.get(reverse("api-v1:listing-detail", args=[listing.pk])).json()

    assert {field: data[field] for field in (
        "sku_id",
        "price",
        "condition",
        "observed_at",
        "price_kind",
        "trade_side",
    )} == {
        "sku_id": None,
        "price": None,
        "condition": None,
        "observed_at": None,
        "price_kind": None,
        "trade_side": None,
    }
    assert data["resolution_confidence"] == "0.0000"


def test_pricepoint_representation_has_exact_fields_precision_dates_and_utc_time(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
    pricepoint_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    pricepoint = pricepoint_factory(
        sku=sku,
        median=Decimal("20000.1250"),
        p25=Decimal("19000.5000"),
        p75=Decimal("21000.7500"),
        mad=Decimal("1500.2500"),
        calculated_at=datetime(2026, 8, 8, 16, 30, 0, tzinfo=UTC),
    )
    _login_with_views(client, user_factory, grant_view_permissions, Sku, PricePoint)

    result = _page(
        client.get(reverse("api-v1:sku-pricepoint-list", args=[sku.pk]))
    )["results"][0]

    assert set(result) == PRICEPOINT_FIELDS
    assert result["id"] == pricepoint.pk
    assert result["sku_id"] == sku.pk
    assert result["day"] == "2026-08-08"
    assert result["median"] == "20000.1250"
    assert result["p25"] == "19000.5000"
    assert result["p75"] == "21000.7500"
    assert result["mad"] == "1500.2500"
    assert result["window_start_day"] == "2026-05-10"
    assert result["window_end_day"] == "2026-08-08"
    assert result["calculated_at"] == "2026-08-08T16:30:00Z"


def test_legacy_pricepoint_audit_metadata_remains_null(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
    pricepoint_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    pricepoint_factory(
        sku=sku,
        mad=None,
        window_start_day=None,
        window_end_day=None,
        calculated_at=None,
        calculation_contract_version=None,
    )
    _login_with_views(client, user_factory, grant_view_permissions, Sku, PricePoint)

    result = _page(
        client.get(reverse("api-v1:sku-pricepoint-list", args=[sku.pk]))
    )["results"][0]

    assert {field: result[field] for field in (
        "mad",
        "window_start_day",
        "window_end_day",
        "calculated_at",
        "calculation_contract_version",
    )} == {
        "mad": None,
        "window_start_day": None,
        "window_end_day": None,
        "calculated_at": None,
        "calculation_contract_version": None,
    }


def test_dealflag_feed_has_exact_nested_derived_evidence_and_legacy_reason(
    client,
    user_factory,
    grant_view_permissions,
    dealflag_factory,
):
    from catalogue.models import Sku
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    reason = "legacy arbitrary reason must pass through unchanged"
    dealflag = dealflag_factory(
        score=Decimal("-12.3456"),
        reason=reason,
        flagged_at=datetime(2026, 8, 9, 5, 6, 7, tzinfo=UTC),
    )
    _login_with_views(
        client,
        user_factory,
        grant_view_permissions,
        Sku,
        Listing,
        PricePoint,
        DealFlag,
    )

    result = _page(client.get(reverse("api-v1:dealflag-list")))["results"][0]

    assert set(result) == DEALFLAG_FIELDS
    assert set(result["sku"]) == SKU_SUMMARY_FIELDS
    assert set(result["listing"]) == LISTING_FIELDS
    assert set(result["baseline_pricepoint"]) == PRICEPOINT_FIELDS
    assert result["id"] == dealflag.pk
    assert result["sku"]["id"] == dealflag.baseline_pricepoint.sku_id
    assert result["listing"]["id"] == dealflag.listing_id
    assert result["baseline_pricepoint"]["id"] == dealflag.baseline_pricepoint_id
    assert result["score"] == "-12.3456"
    assert result["reason"] == reason
    assert result["flagged_at"] == "2026-08-09T05:06:07Z"


def test_all_derived_representations_exclude_rawlisting_keys_and_values(
    client,
    user_factory,
    grant_view_permissions,
    dealflag_factory,
):
    from catalogue.models import Sku
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    dealflag_factory()
    _login_with_views(
        client,
        user_factory,
        grant_view_permissions,
        Sku,
        Listing,
        PricePoint,
        DealFlag,
    )

    encoded = json.dumps(_page(client.get(reverse("api-v1:dealflag-list"))))

    for forbidden in (
        "raw_listing",
        "raw_title",
        "raw_price_text",
        "source",
        "url",
        "seller",
        "payload",
        "occurred_at",
        "fetched_at",
        "RAW-TITLE-MUST-NOT-LEAK",
        "RAW-PRICE-MUST-NOT-LEAK",
        "MUST-NOT-LEAK",
    ):
        assert forbidden not in encoded


def test_sku_collection_is_ordered_and_uses_fixed_page_number_pagination(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
):
    from catalogue.models import Sku

    for number in range(26):
        sku_factory(
            brand=f"Brand-{number:02d}",
            model="Model",
            variant="",
        )
    _login_with_views(client, user_factory, grant_view_permissions, Sku)
    url = reverse("api-v1:sku-list")

    first = _page(client.get(url, {"page_size": 100}))
    second = _page(client.get(url, {"page": 2}))

    assert first["count"] == 26
    assert len(first["results"]) == 25
    assert first["previous"] is None
    assert first["next"] is not None
    assert [row["brand"] for row in first["results"]] == [
        f"Brand-{number:02d}" for number in range(25)
    ]
    assert second["count"] == 26
    assert [row["brand"] for row in second["results"]] == ["Brand-25"]
    assert second["previous"] is not None
    assert second["next"] is None


def test_pricepoint_history_orders_oldest_first_with_stable_condition_tie_break(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
    pricepoint_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    later = pricepoint_factory(sku=sku, day=date(2026, 8, 9), condition="used")
    same_day_used = pricepoint_factory(sku=sku, day=date(2026, 8, 8), condition="used")
    same_day_new = pricepoint_factory(sku=sku, day=date(2026, 8, 8), condition="new")
    _login_with_views(client, user_factory, grant_view_permissions, Sku, PricePoint)

    results = _page(
        client.get(reverse("api-v1:sku-pricepoint-list", args=[sku.pk]))
    )["results"]

    assert [row["id"] for row in results] == [
        same_day_new.pk,
        same_day_used.pk,
        later.pk,
    ]


def test_pricepoint_history_supports_only_exact_condition_filter(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
    pricepoint_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    pricepoint_factory(sku=sku, day=date(2026, 8, 8), condition="used")
    expected = pricepoint_factory(sku=sku, day=date(2026, 8, 8), condition="new")
    _login_with_views(client, user_factory, grant_view_permissions, Sku, PricePoint)
    url = reverse("api-v1:sku-pricepoint-list", args=[sku.pk])

    filtered = _page(client.get(url, {"condition": "new"}))

    assert filtered["count"] == 1
    assert [row["id"] for row in filtered["results"]] == [expected.pk]
    assert client.get(url, {"condition": "refurbished"}).status_code == 400


def test_dealflag_feed_orders_newest_first_then_id_ascending(
    client,
    user_factory,
    grant_view_permissions,
    dealflag_factory,
):
    from catalogue.models import Sku
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    older = dealflag_factory(flagged_at=datetime(2026, 8, 8, 0, 0, 0, tzinfo=UTC))
    tied_at = datetime(2026, 8, 9, 0, 0, 0, tzinfo=UTC)
    tie_a = dealflag_factory(flagged_at=tied_at)
    tie_b = dealflag_factory(flagged_at=tied_at)
    newest = dealflag_factory(flagged_at=datetime(2026, 8, 10, 0, 0, 0, tzinfo=UTC))
    _login_with_views(
        client,
        user_factory,
        grant_view_permissions,
        Sku,
        Listing,
        PricePoint,
        DealFlag,
    )

    results = _page(client.get(reverse("api-v1:dealflag-list")))["results"]

    assert [row["id"] for row in results] == [
        newest.pk,
        tie_a.pk,
        tie_b.pk,
        older.pk,
    ]


def test_empty_collections_return_successful_stable_envelopes(
    client,
    user_factory,
    grant_view_permissions,
    sku_factory,
):
    from catalogue.models import Sku
    from listings.models import Listing
    from pricing.models import DealFlag, PricePoint

    sku = sku_factory()
    _login_with_views(
        client,
        user_factory,
        grant_view_permissions,
        Sku,
        Listing,
        PricePoint,
        DealFlag,
    )

    for url in (
        reverse("api-v1:sku-pricepoint-list", args=[sku.pk]),
        reverse("api-v1:dealflag-list"),
    ):
        assert _page(client.get(url)) == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }


@pytest.mark.parametrize(
    ("method", "route_name", "route_args"),
    [
        ("post", "api-v1:sku-list", None),
        ("put", "api-v1:sku-detail", "sku"),
        ("patch", "api-v1:listing-detail", "listing"),
        ("delete", "api-v1:listing-detail", "listing"),
        ("post", "api-v1:sku-pricepoint-list", "sku"),
        ("post", "api-v1:dealflag-list", None),
    ],
)
def test_exposed_routes_reject_unsafe_methods(
    client,
    user_factory,
    sku_factory,
    listing_factory,
    method,
    route_name,
    route_args,
):
    sku = sku_factory()
    listing = listing_factory(sku=sku)
    client.force_login(user_factory(is_superuser=True))
    object_map = {"sku": sku.pk, "listing": listing.pk}
    args = None if route_args is None else [object_map[route_args]]
    url = reverse(route_name, args=args)

    response = getattr(client, method)(url, data={}, content_type="application/json")

    assert response.status_code == 405


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/listings/",
        "/api/v1/price-points/",
        "/api/v1/raw-listings/",
        "/api/v1/sku-aliases/",
        "/api/v1/outcomes/",
    ],
)
def test_no_generic_or_out_of_scope_api_routes(client, user_factory, path):
    client.force_login(user_factory(is_superuser=True))

    with pytest.raises(Resolver404):
        resolve(path)
    assert client.get(path).status_code == 404


def test_pricing_reads_do_not_execute_pricing_or_create_evidence(
    client,
    user_factory,
    sku_factory,
):
    from pricing.models import DealFlag, PricePoint

    sku = sku_factory()
    client.force_login(user_factory(is_superuser=True))
    before = (PricePoint.objects.count(), DealFlag.objects.count())

    with (
        patch(
            "pricing.baselines.build_pricepoint",
            side_effect=AssertionError("HTTP read executed baseline construction"),
        ),
        patch(
            "pricing.scoring.score_listing",
            side_effect=AssertionError("HTTP read executed deal scoring"),
        ),
        patch(
            "pricing.management.commands.price_listings.Command.handle",
            side_effect=AssertionError("HTTP read executed price_listings"),
        ),
    ):
        history_response = client.get(
            reverse("api-v1:sku-pricepoint-list", args=[sku.pk])
        )
        feed_response = client.get(reverse("api-v1:dealflag-list"))

    assert history_response.status_code == 200
    assert feed_response.status_code == 200
    assert (PricePoint.objects.count(), DealFlag.objects.count()) == before
