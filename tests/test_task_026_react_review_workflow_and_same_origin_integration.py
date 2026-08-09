import json
import re
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import NoReverseMatch, reverse


ROOT = Path(__file__).resolve().parents[1]
UTC = dt_timezone.utc


def _required_reverse(name, args=None):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        pytest.fail(f"TASK_026 implementation must register {name}")


@pytest.fixture
def source(db):
    from sources.models import Source

    return Source.objects.create(
        name=f"task_026_{uuid4().hex}",
        base_url="https://task026.example.invalid",
        terms_notes="synthetic TASK_026 fixture",
        rate_limit=None,
    )


@pytest.fixture
def raw_listing_factory(db, source):
    from ingestion.models import RawListing

    def make(**overrides):
        marker = uuid4().hex
        values = {
            "source": source,
            "raw_title": f"Synthetic TASK 026 GPU {marker}",
            "raw_price": Decimal("15500.00"),
            "raw_price_text": "PHP 15,500 asking",
            "url": f"https://task026.example.invalid/{marker}",
            "seller": f"private-{marker}",
            "fetched_at": datetime(2026, 8, 9, 4, 5, 6, tzinfo=UTC),
            "occurred_at": datetime(2026, 8, 8, 3, 4, 5, tzinfo=UTC),
            "external_id": f"task-026-{marker}",
            "payload": {"private": marker},
        }
        values.update(overrides)
        return RawListing.objects.create(**values)

    return make


@pytest.fixture
def sku_factory(db):
    from catalogue.models import Sku

    def make(**overrides):
        marker = uuid4().hex
        values = {
            "brand": "Synthetic",
            "model": f"GPU {marker}",
            "variant": "",
            "category": "gpu",
            "launch_msrp": Decimal("34995.00"),
            "launch_date": date(2026, 1, 1),
        }
        values.update(overrides)
        return Sku.objects.create(**values)

    return make


@pytest.fixture
def listing_factory(db, raw_listing_factory):
    from listings.models import Listing

    def make(**overrides):
        raw_listing = overrides.pop("raw_listing", None) or raw_listing_factory()
        values = {
            "raw_listing": raw_listing,
            "sku": None,
            "price": raw_listing.raw_price,
            "condition": "used",
            "location": "Metro Manila",
            "resolution_confidence": Decimal("0.0000"),
            "resolution_method": "unresolved",
            "resolved_at": datetime(2026, 8, 9, 5, 6, 7, tzinfo=UTC),
            "reviewed_unresolved_at": None,
            "observed_at": raw_listing.occurred_at or raw_listing.fetched_at,
            "price_kind": "asking",
            "trade_side": None,
        }
        values.update(overrides)
        return Listing.objects.create(**values)

    return make


@pytest.fixture
def user_factory(db):
    def make(*, is_active=True, is_staff=True):
        return get_user_model().objects.create_user(
            username=f"task026-{uuid4().hex}",
            password="test-password",
            is_active=is_active,
            is_staff=is_staff,
        )

    return make


def _grant(user, model, *actions):
    content_type = ContentType.objects.get_for_model(model)
    codenames = {f"{action}_{model._meta.model_name}" for action in actions}
    permissions = Permission.objects.filter(
        content_type=content_type,
        codename__in=codenames,
    )
    assert set(permissions.values_list("codename", flat=True)) == codenames
    user.user_permissions.add(*permissions)


def _page(response):
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    return body


@pytest.mark.django_db
def test_task_026_routes_are_exact_and_existing_phase6_routes_remain_stable():
    assert _required_reverse("api-v1:review-listing-list") == (
        "/api/v1/reviews/listings/"
    )
    assert _required_reverse("api-v1:review-listing-detail", [23]) == (
        "/api/v1/reviews/listings/23/"
    )
    assert _required_reverse("api-v1:session-csrf") == "/api/v1/session/csrf/"
    assert _required_reverse("login") == "/auth/login/"
    assert _required_reverse("logout") == "/auth/logout/"

    assert reverse("api-v1:review-mark-reviewed-unresolved", args=[23]) == (
        "/api/v1/reviews/listings/23/mark-reviewed-unresolved/"
    )
    assert reverse("api-v1:review-confirm-sku", args=[23]) == (
        "/api/v1/reviews/listings/23/confirm-sku/"
    )
    assert reverse("api-v1:sku-list") == "/api/v1/skus/"
    assert reverse("api-v1:dealflag-list") == "/api/v1/deal-flags/"


@pytest.mark.django_db
def test_review_queue_projection_is_exact_decimal_safe_and_excludes_private_raw_data(
    client,
    listing_factory,
    user_factory,
):
    from listings.models import Listing
    from listings.normalisation import normalise_title

    actor = user_factory()
    _grant(actor, Listing, "change")
    client.force_login(actor)
    listing = listing_factory(
        resolution_method="fuzzy_match",
        resolution_confidence=Decimal("0.4321"),
    )

    result = _page(client.get(_required_reverse("api-v1:review-listing-list")))[
        "results"
    ][0]

    assert set(result) == {"id", "raw_evidence", "derived_listing", "current_sku"}
    assert result["id"] == listing.pk
    assert result["raw_evidence"] == {
        "raw_title": listing.raw_listing.raw_title,
        "normalised_title": normalise_title(listing.raw_listing.raw_title),
        "raw_price_text": listing.raw_listing.raw_price_text,
        "source": {
            "id": listing.raw_listing.source_id,
            "name": listing.raw_listing.source.name,
        },
        "url": listing.raw_listing.url,
        "occurred_at": "2026-08-08T03:04:05Z",
        "fetched_at": "2026-08-09T04:05:06Z",
    }
    assert result["derived_listing"] == {
        "price": "15500.00",
        "condition": "used",
        "location": "Metro Manila",
        "resolution_method": "fuzzy_match",
        "resolution_confidence": "0.4321",
        "resolved_at": "2026-08-09T05:06:07Z",
        "reviewed_unresolved_at": None,
        "observed_at": "2026-08-08T03:04:05Z",
        "price_kind": "asking",
        "trade_side": None,
    }
    assert result["current_sku"] is None
    assert not {
        "raw_listing_id",
        "raw_price",
        "seller",
        "payload",
        "external_id",
        "base_url",
        "terms_notes",
        "last_successful_fetch",
    }.intersection(result["raw_evidence"])


@pytest.mark.django_db
def test_review_queue_uses_only_the_primary_predicate_oldest_order_and_25_rows(
    client,
    listing_factory,
    raw_listing_factory,
    sku_factory,
    user_factory,
):
    from django.db.models.functions import Coalesce
    from listings.models import Listing

    actor = user_factory()
    _grant(actor, Listing, "change")
    client.force_login(actor)

    expected = []
    for index in range(26):
        raw = raw_listing_factory(
            occurred_at=None,
            fetched_at=datetime(2026, 8, 9, 1, 0, index, tzinfo=UTC),
        )
        expected.append(listing_factory(raw_listing=raw))

    fuzzy = listing_factory(resolution_method="fuzzy_match")
    null_exact = listing_factory(resolution_method="exact_alias")
    null_human = listing_factory(resolution_method="human_confirmed")
    reviewed = listing_factory(
        reviewed_unresolved_at=datetime(2026, 8, 9, 7, 0, tzinfo=UTC)
    )
    resolved = listing_factory(
        sku=sku_factory(),
        resolution_method="human_confirmed",
        resolution_confidence=Decimal("1.0000"),
    )

    first_page = _page(client.get(_required_reverse("api-v1:review-listing-list")))
    second_page = _page(
        client.get(_required_reverse("api-v1:review-listing-list"), {"page": 2})
    )
    ids = [row["id"] for row in first_page["results"] + second_page["results"]]

    ordered_expected = list(
        Listing.objects.filter(
            pk__in=[item.pk for item in expected] + [fuzzy.pk, null_exact.pk, null_human.pk]
        )
        .annotate(
            review_order=Coalesce(
                "raw_listing__occurred_at",
                "raw_listing__fetched_at",
            )
        )
        .order_by("review_order", "pk")
        .values_list("pk", flat=True)
    )
    assert first_page["count"] == 29
    assert len(first_page["results"]) == 25
    assert ids == ordered_expected
    assert reviewed.pk not in ids
    assert resolved.pk not in ids
    assert {fuzzy.pk, null_exact.pk, null_human.pk}.issubset(ids)


@pytest.mark.django_db
def test_review_detail_supports_existing_sku_correction_and_exact_missing_error(
    client,
    listing_factory,
    sku_factory,
    user_factory,
):
    from listings.models import Listing
    from listings.normalisation import normalise_title

    actor = user_factory()
    _grant(actor, Listing, "change")
    client.force_login(actor)
    sku = sku_factory(
        brand="NVIDIA",
        model="RTX 4070",
        variant="Founders Edition",
    )
    listing = listing_factory(
        sku=sku,
        resolution_method="human_confirmed",
        resolution_confidence=Decimal("1.0000"),
    )

    response = client.get(
        _required_reverse("api-v1:review-listing-detail", [listing.pk])
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "raw_evidence", "derived_listing", "current_sku"}
    assert body["id"] == listing.pk
    assert body["raw_evidence"] == {
        "raw_title": listing.raw_listing.raw_title,
        "normalised_title": normalise_title(listing.raw_listing.raw_title),
        "raw_price_text": listing.raw_listing.raw_price_text,
        "source": {
            "id": listing.raw_listing.source_id,
            "name": listing.raw_listing.source.name,
        },
        "url": listing.raw_listing.url,
        "occurred_at": "2026-08-08T03:04:05Z",
        "fetched_at": "2026-08-09T04:05:06Z",
    }
    assert body["derived_listing"] == {
        "price": "15500.00",
        "condition": "used",
        "location": "Metro Manila",
        "resolution_method": "human_confirmed",
        "resolution_confidence": "1.0000",
        "resolved_at": "2026-08-09T05:06:07Z",
        "reviewed_unresolved_at": None,
        "observed_at": "2026-08-08T03:04:05Z",
        "price_kind": "asking",
        "trade_side": None,
    }
    assert body["current_sku"] == {
        "id": sku.pk,
        "brand": "NVIDIA",
        "model": "RTX 4070",
        "variant": "Founders Edition",
        "category": "gpu",
    }
    assert not {
        "raw_listing_id",
        "raw_price",
        "seller",
        "payload",
        "external_id",
    }.intersection(body["raw_evidence"])
    assert set(body["raw_evidence"]["source"]) == {"id", "name"}

    missing = client.get(_required_reverse("api-v1:review-listing-detail", [999999999]))
    assert missing.status_code == 404
    assert missing.json() == {
        "code": "listing_not_found",
        "detail": "Listing not found.",
    }
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(
            _required_reverse("api-v1:review-listing-detail", [listing.pk])
        ).status_code == 405


@pytest.mark.django_db
def test_review_reads_require_active_staff_listing_change_only(
    client,
    listing_factory,
    user_factory,
):
    from listings.models import Listing

    listing = listing_factory()
    urls = (
        _required_reverse("api-v1:review-listing-list"),
        _required_reverse("api-v1:review-listing-detail", [listing.pk]),
    )
    for url in urls:
        assert client.get(url).status_code == 403

    nonstaff = user_factory(is_staff=False)
    _grant(nonstaff, Listing, "change")
    client.force_login(nonstaff)
    for url in urls:
        assert client.get(url).status_code == 403
    client.logout()

    inactive = user_factory(is_active=False)
    _grant(inactive, Listing, "change")
    client.force_login(inactive)
    for url in urls:
        assert client.get(url).status_code == 403
    client.logout()

    no_permission = user_factory()
    client.force_login(no_permission)
    for url in urls:
        assert client.get(url).status_code == 403
    client.logout()

    actor = user_factory()
    _grant(actor, Listing, "change")
    client.force_login(actor)
    for url in urls:
        assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_existing_sku_list_adds_only_bounded_case_insensitive_q_search(
    client,
    sku_factory,
    user_factory,
):
    from catalogue.models import Sku

    actor = user_factory()
    _grant(actor, Sku, "view")
    client.force_login(actor)
    target = sku_factory(brand="NVIDIA", model="RTX 4070 SUPER", variant="12GB")
    sku_factory(brand="AMD", model="RX 7900 XT", variant="Reference")
    sku_factory(brand="Intel", model="Arc B580", variant="Limited")
    zeta = sku_factory(brand="Zeta", model="ORDERKEY GPU", variant="")
    alpha_z = sku_factory(brand="Alpha", model="ORDERKEY GPU", variant="Z")
    bravo = sku_factory(brand="Bravo", model="ORDERKEY GPU", variant="")
    alpha_a = sku_factory(brand="Alpha", model="ORDERKEY GPU", variant="A")
    url = reverse("api-v1:sku-list")

    searched = _page(client.get(url, {"q": "  rTx 4070  "}))
    assert [row["id"] for row in searched["results"]] == [target.pk]
    assert _page(client.get(url))["count"] == 7
    ordered = _page(client.get(url, {"q": "orderkey"}))
    assert [row["id"] for row in ordered["results"]] == [
        alpha_a.pk,
        alpha_z.pk,
        bravo.pk,
        zeta.pk,
    ]
    assert _page(client.get(url, {"q": "rt"}))["count"] == 1
    assert _page(client.get(url, {"q": "x" * 100}))["count"] == 0

    too_short = client.get(url, {"q": "x"})
    assert too_short.status_code == 400
    assert "q" in too_short.json()
    blank = client.get(url, {"q": "   "})
    assert blank.status_code == 400
    assert "q" in blank.json()
    too_long = client.get(url, {"q": f" {'x' * 101} "})
    assert too_long.status_code == 400
    assert "q" in too_long.json()


@pytest.mark.django_db
def test_csrf_bootstrap_sets_cookie_returns_masked_token_and_is_get_only():
    client = Client(enforce_csrf_checks=True)
    url = _required_reverse("api-v1:session-csrf")

    without_token = Client(enforce_csrf_checks=True).post(
        url,
        data="{}",
        content_type="application/json",
    )
    assert without_token.status_code == 403

    response = client.get(url)
    assert response.status_code == 200
    assert set(response.json()) == {"csrf_token"}
    assert isinstance(response.json()["csrf_token"], str)
    assert len(response.json()["csrf_token"]) == 64
    assert "csrftoken" in response.cookies
    assert "no-store" in response["Cache-Control"]
    with_token = client.post(
        url,
        data="{}",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=response.json()["csrf_token"],
    )
    assert with_token.status_code == 405


@pytest.mark.django_db
def test_mounted_django_login_safe_next_and_csrf_protected_post_logout(user_factory):
    actor = user_factory()
    client = Client(enforce_csrf_checks=True)
    login_url = _required_reverse("login")
    logout_url = _required_reverse("logout")

    login_page = client.get(login_url, {"next": "/reviews/7"})
    assert login_page.status_code == 200
    html = login_page.content.decode()
    assert 'name="username"' in html
    assert 'name="password"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'name="next"' in html
    assert "/reviews/7" in html

    missing_csrf = Client(enforce_csrf_checks=True).post(
        login_url,
        {"username": actor.username, "password": "test-password"},
    )
    assert missing_csrf.status_code == 403

    token = client.cookies["csrftoken"].value
    signed_in = client.post(
        f"{login_url}?next=/reviews/7",
        {
            "username": actor.username,
            "password": "test-password",
            "csrfmiddlewaretoken": token,
            "next": "/reviews/7",
        },
    )
    assert signed_in.status_code == 302
    assert signed_in["Location"] == "/reviews/7"

    assert client.get(logout_url).status_code == 405
    rotated_token = client.cookies["csrftoken"].value
    signed_out = client.post(logout_url, HTTP_X_CSRFTOKEN=rotated_token)
    assert signed_out.status_code == 302
    assert signed_out["Location"] == "/auth/login/"

    client.get(login_url)
    token = client.cookies["csrftoken"].value
    external_next = client.post(
        f"{login_url}?next=https://evil.example/steal",
        {
            "username": actor.username,
            "password": "test-password",
            "csrfmiddlewaretoken": token,
            "next": "https://evil.example/steal",
        },
    )
    assert external_next.status_code == 302
    assert external_next["Location"] == "/deals"


@pytest.mark.django_db
def test_built_spa_direct_navigation_and_server_namespaces_are_disjoint(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    marker = "TASK_026_BUILT_REACT_INDEX"
    (dist / "index.html").write_text(f"<main>{marker}</main>")

    with override_settings(FRONTEND_DIST_DIR=dist):
        client = Client()
        for path in (
            "/",
            "/deals",
            "/skus/17",
            "/reviews",
            "/reviews/23",
            "/unknown-product-path",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert marker in response.content.decode()

        for path in (
            "/api/unknown/",
            "/admin/unknown/",
            "/auth/unknown/",
            "/static/unknown.css",
        ):
            response = client.get(path)
            assert marker not in response.content.decode()


@pytest.mark.django_db
def test_product_route_returns_503_when_the_built_spa_index_is_missing(tmp_path):
    missing_dist = tmp_path / "missing-dist"

    with override_settings(FRONTEND_DIST_DIR=missing_dist):
        response = Client().get("/reviews")

    assert response.status_code == 503


@pytest.mark.django_db
def test_collected_admin_and_frontend_assets_are_served_with_debug_false(
    tmp_path,
):
    from django.conf import settings

    assert settings.STATIC_URL == "/static/"
    assert settings.STATIC_ROOT == ROOT / "staticfiles"
    assert settings.FRONTEND_DIST_DIR == ROOT / "frontend" / "dist"
    security_index = settings.MIDDLEWARE.index(
        "django.middleware.security.SecurityMiddleware"
    )
    whitenoise_index = settings.MIDDLEWARE.index(
        "whitenoise.middleware.WhiteNoiseMiddleware"
    )
    assert whitenoise_index == security_index + 1
    assert (
        settings.STORAGES["staticfiles"]["BACKEND"]
        == "whitenoise.storage.CompressedStaticFilesStorage"
    )
    assert "whitenoise>=6.12,<6.13" in (ROOT / "requirements.txt").read_text().splitlines()

    dist = ROOT / "frontend" / "dist"
    built_index = dist / "index.html"
    assert built_index.is_file(), "Run the frozen production frontend build first."
    asset_urls = re.findall(
        r'(?:src|href)="(/static/frontend/[^"]+)"',
        built_index.read_text(),
    )
    assert asset_urls, "The generated index must reference production static assets."
    static_root = tmp_path / "staticfiles"

    with override_settings(
        DEBUG=False,
        STATIC_ROOT=static_root,
        STATICFILES_DIRS=[("frontend", dist)],
        FRONTEND_DIST_DIR=dist,
    ):
        call_command("collectstatic", interactive=False, verbosity=0)
        client = Client()
        admin_login = client.get("/admin/login/")
        assert admin_login.status_code == 200
        assert re.search(r'href="/static/admin/css/base[^\"]*\.css"', admin_login.content.decode())
        assert client.get("/static/admin/css/base.css").status_code == 200
        for asset_url in asset_urls:
            assert client.get(asset_url).status_code == 200


def test_docker_and_generated_file_boundaries_are_explicit():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "node:24.18.0" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=" in dockerfile
    assert "frontend/dist" in dockerfile

    entrypoint = ROOT / "docker-entrypoint.sh"
    assert entrypoint.is_file()
    entrypoint_text = entrypoint.read_text()
    assert "collectstatic --noinput" in entrypoint_text
    assert 'exec "$@"' in entrypoint_text

    dockerignore = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {
        "frontend/node_modules",
        "frontend/dist",
        "frontend/coverage",
        "frontend/.vite",
    }.issubset(dockerignore)


@pytest.mark.django_db
def test_task_026_requires_no_model_or_migration_change():
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
