"""Frozen TASK_037A pre-deployment audit remediation acceptance tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from django.contrib.auth.models import Permission
from django.urls import reverse


REPO_ROOT = Path(__file__).resolve().parent.parent


def _grant(user, permission_name):
    app_label, codename = permission_name.split(".", 1)
    permission = Permission.objects.get(
        content_type__app_label=app_label,
        codename=codename,
    )
    user.user_permissions.add(permission)


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="task037a_staff",
        password="not-a-production-password",
        is_active=True,
        is_staff=True,
    )


@pytest.fixture
def trade_payload():
    return {
        "trade_type": "buy",
        "occurred_on": "2026-08-01",
        "counterparty": "TASK_037A Counterparty",
        "item": "TASK_037A audit fixture GPU",
        "condition": "used",
        "price": "15500",
    }


@pytest.mark.django_db
def test_personal_trade_form_denies_staff_without_add_rawlisting(
    client,
    staff_user,
):
    client.force_login(staff_user)

    response = client.get(
        reverse("admin:ingestion_rawlisting_log_personal_trade")
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_personal_trade_post_denies_without_permission_and_writes_nothing(
    client,
    staff_user,
    trade_payload,
):
    from ingestion.models import RawListing, Swap

    client.force_login(staff_user)

    response = client.post(
        reverse("admin:ingestion_rawlisting_log_personal_trade"),
        trade_payload,
    )

    assert response.status_code == 403
    assert RawListing.objects.count() == 0
    assert Swap.objects.count() == 0


@pytest.mark.django_db
def test_add_rawlisting_permission_authorizes_only_the_dedicated_trade_form(
    client,
    staff_user,
    trade_payload,
):
    from ingestion.models import RawListing

    _grant(staff_user, "ingestion.add_rawlisting")
    client.force_login(staff_user)

    form_url = reverse("admin:ingestion_rawlisting_log_personal_trade")
    assert client.get(form_url).status_code == 200
    assert client.post(form_url, trade_payload).status_code == 302
    assert RawListing.objects.count() == 1

    # The dedicated permission gate must not reopen Django's generic add form.
    assert client.get(reverse("admin:ingestion_rawlisting_add")).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "granted_permissions",
    [
        (),
        ("pricing.view_dealflag",),
        ("outcomes.view_outcome",),
    ],
)
def test_outcome_worklist_requires_both_view_permissions(
    client,
    staff_user,
    granted_permissions,
):
    for permission_name in granted_permissions:
        _grant(staff_user, permission_name)
    client.force_login(staff_user)

    response = client.get(reverse("admin:outcomes_outcome_untracked"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_outcome_worklist_allows_staff_with_both_view_permissions(
    client,
    staff_user,
):
    _grant(staff_user, "pricing.view_dealflag")
    _grant(staff_user, "outcomes.view_outcome")
    client.force_login(staff_user)

    response = client.get(reverse("admin:outcomes_outcome_untracked"))

    assert response.status_code == 200


def _settings_process(*, public_base_url, proxy_gate, assert_secure_contract=False):
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SECRET_KEY": "task037a-settings-secret",
            "DJANGO_SELLER_PSEUDONYM_KEY": "task037a-seller-key",
            "POSTGRES_DB": "task037a",
            "POSTGRES_USER": "task037a",
            "POSTGRES_PASSWORD": "task037a",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5432",
            "PRICEWATCHPH_PUBLIC_BASE_URL": public_base_url,
        }
    )
    if proxy_gate is None:
        environment.pop("DJANGO_BEHIND_HTTPS_PROXY", None)
    else:
        environment["DJANGO_BEHIND_HTTPS_PROXY"] = proxy_gate

    command = "from django.conf import Settings; Settings('config.settings')"
    if assert_secure_contract:
        command = (
            "from django.conf import Settings; "
            "s = Settings('config.settings'); "
            "assert s.SECURE_PROXY_SSL_HEADER == "
            "('HTTP_X_FORWARDED_PROTO', 'https'); "
            "assert s.SECURE_SSL_REDIRECT is True; "
            "assert s.SESSION_COOKIE_SECURE is True; "
            "assert s.CSRF_COOKIE_SECURE is True"
        )

    return subprocess.run(
        [
            sys.executable,
            "-c",
            command,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("proxy_gate", [None, "0", "true"])
def test_https_public_origin_fails_closed_without_literal_proxy_gate_one(
    proxy_gate,
):
    result = _settings_process(
        public_base_url="https://pricewatch.task037a.invalid",
        proxy_gate=proxy_gate,
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_https_public_origin_with_proxy_gate_one_enables_full_security_contract():
    result = _settings_process(
        public_base_url="https://pricewatch.task037a.invalid",
        proxy_gate="1",
        assert_secure_contract=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_local_http_origin_remains_valid_with_proxy_gate_disabled():
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SECRET_KEY": "task037a-settings-secret",
            "DJANGO_SELLER_PSEUDONYM_KEY": "task037a-seller-key",
            "POSTGRES_DB": "task037a",
            "POSTGRES_USER": "task037a",
            "POSTGRES_PASSWORD": "task037a",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5432",
            "PRICEWATCHPH_PUBLIC_BASE_URL": "http://localhost",
            "DJANGO_BEHIND_HTTPS_PROXY": "0",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_database_service_receives_only_required_postgresql_variables():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    database = compose["services"]["db"]

    assert "env_file" not in database
    assert set(database.get("environment", {})) == {
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    }
    for variable_name, value in database["environment"].items():
        assert f"${{{variable_name}" in value


def test_application_peers_keep_an_application_environment_source():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())

    for service_name in ("migrate", "web"):
        assert compose["services"][service_name].get("env_file")

    if "scheduler" in compose["services"]:
        assert (
            compose["services"]["scheduler"].get("env_file")
            == compose["services"]["web"].get("env_file")
        )

    if "backup" in compose["services"]:
        assert "env_file" not in compose["services"]["backup"]

    if "caddy" in compose["services"]:
        caddy = compose["services"]["caddy"]
        assert "env_file" not in caddy
        assert set(caddy["environment"]) == {"PRICEWATCHPH_PUBLIC_BASE_URL"}
