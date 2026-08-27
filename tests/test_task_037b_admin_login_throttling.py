"""Frozen TASK_037B administrator login throttling acceptance tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse


REPO_ROOT = Path(__file__).resolve().parent.parent
FAILURE_LIMIT = 5
GENERIC_LOCKOUT_BODY = b"Too many login attempts. Please try again later."


@pytest.fixture
def administrator(django_user_model):
    return django_user_model.objects.create_user(
        username="task037b_admin",
        password="task037b-test-password",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


def _post_login(
    client,
    url,
    *,
    username="task037b_unknown",
    password="wrong-password",
    remote_addr="198.51.100.10",
    forwarded_for=None,
):
    request_meta = {"REMOTE_ADDR": remote_addr}
    if forwarded_for is not None:
        request_meta["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return client.post(
        url,
        {
            "username": username,
            "password": password,
            "next": "/admin/",
        },
        **request_meta,
    )


def _assert_throttled(response):
    assert response.status_code == 429
    assert response.content == GENERIC_LOCKOUT_BODY


def test_requirement_declares_supported_django_axes_with_ipware_extra():
    requirements = (REPO_ROOT / "requirements.txt").read_text().splitlines()

    assert requirements.count("django-axes[ipware]>=8.3.1,<9") == 1


def test_settings_use_postgresql_backed_axes_with_the_exact_policy():
    from datetime import timedelta

    assert "axes" in settings.INSTALLED_APPS
    assert settings.AUTHENTICATION_BACKENDS == [
        "axes.backends.AxesStandaloneBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
    assert settings.MIDDLEWARE[-1] == "axes.middleware.AxesMiddleware"
    assert settings.AXES_HANDLER == "axes.handlers.database.AxesDatabaseHandler"
    assert settings.AXES_LOCKOUT_PARAMETERS == ["ip_address"]
    assert settings.AXES_FAILURE_LIMIT == FAILURE_LIMIT
    assert settings.AXES_COOLOFF_TIME == timedelta(minutes=15)
    assert settings.AXES_USE_ATTEMPT_EXPIRATION is True
    assert settings.AXES_RESET_ON_SUCCESS is True
    assert settings.AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT is False
    assert settings.AXES_HTTP_RESPONSE_CODE == 429
    assert settings.AXES_COOLOFF_MESSAGE == GENERIC_LOCKOUT_BODY.decode()
    assert settings.AXES_DISABLE_ACCESS_LOG is True
    assert settings.AXES_ENABLE_ACCESS_FAILURE_LOG is False
    assert settings.AXES_ENABLE_ADMIN is False
    assert settings.AXES_SENSITIVE_PARAMETERS == ["username", "ip_address"]
    assert settings.AXES_ONLY_ADMIN_SITE is False
    assert settings.AXES_IPWARE_PROXY_ORDER == "left-most"
    assert settings.AXES_IPWARE_PROXY_COUNT == 0
    assert settings.AXES_IPWARE_META_PRECEDENCE_ORDER == ("REMOTE_ADDR",)


def _proxy_settings_process():
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SECRET_KEY": "task037b-settings-secret",
            "DJANGO_SELLER_PSEUDONYM_KEY": "task037b-seller-key",
            "POSTGRES_DB": "task037b",
            "POSTGRES_USER": "task037b",
            "POSTGRES_PASSWORD": "task037b",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5432",
            "PRICEWATCHPH_PUBLIC_BASE_URL": "https://pricewatch.task037b.invalid",
            "DJANGO_BEHIND_HTTPS_PROXY": "1",
        }
    )
    command = (
        "from django.conf import Settings; "
        "s = Settings('config.settings'); "
        "assert s.AXES_IPWARE_PROXY_COUNT == 0; "
        "assert s.AXES_IPWARE_PROXY_ORDER == 'left-most'; "
        "assert s.AXES_IPWARE_META_PRECEDENCE_ORDER == "
        "('HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR')"
    )
    return subprocess.run(
        [sys.executable, "-c", command],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_proxy_gate_selects_only_the_approved_caddy_client_ip_contract():
    result = _proxy_settings_process()

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.django_db
def test_four_failures_are_normal_and_fifth_failure_throttles():
    client = Client()
    login_url = reverse("admin:login")

    for _ in range(FAILURE_LIMIT - 1):
        response = _post_login(client, login_url)
        assert response.status_code == 200
        assert response.content != GENERIC_LOCKOUT_BODY

    _assert_throttled(_post_login(client, login_url))


@pytest.mark.django_db
def test_changing_username_or_login_route_does_not_bypass_ip_throttle():
    client = Client()
    admin_login = reverse("admin:login")
    application_login = reverse("login")
    attempts = (
        (admin_login, "task037b_unknown_1"),
        (application_login, "task037b_unknown_2"),
        (admin_login, "task037b_unknown_3"),
        (application_login, "task037b_unknown_4"),
    )

    for url, username in attempts:
        assert _post_login(client, url, username=username).status_code == 200

    _assert_throttled(
        _post_login(client, admin_login, username="task037b_unknown_5")
    )
    _assert_throttled(
        _post_login(client, application_login, username="task037b_unknown_6")
    )


@pytest.mark.django_db
def test_successful_login_below_limit_resets_the_source_address(administrator):
    client = Client()
    login_url = reverse("admin:login")

    for _ in range(FAILURE_LIMIT - 1):
        assert _post_login(client, login_url).status_code == 200

    signed_in = _post_login(
        client,
        login_url,
        username=administrator.username,
        password="task037b-test-password",
    )
    assert signed_in.status_code == 302
    assert signed_in.headers["Location"] == "/admin/"

    fresh_client = Client()
    for _ in range(FAILURE_LIMIT - 1):
        assert _post_login(fresh_client, login_url).status_code == 200
    _assert_throttled(_post_login(fresh_client, login_url))


@pytest.mark.django_db
def test_throttled_response_does_not_disclose_account_existence(administrator):
    login_url = reverse("admin:login")

    nonexistent_client = Client()
    for _ in range(FAILURE_LIMIT - 1):
        _post_login(
            nonexistent_client,
            login_url,
            username="task037b_does_not_exist",
            remote_addr="198.51.100.20",
        )
    nonexistent = _post_login(
        nonexistent_client,
        login_url,
        username="task037b_does_not_exist",
        remote_addr="198.51.100.20",
    )

    existing_client = Client()
    for _ in range(FAILURE_LIMIT - 1):
        _post_login(
            existing_client,
            login_url,
            username=administrator.username,
            remote_addr="198.51.100.21",
        )
    existing = _post_login(
        existing_client,
        login_url,
        username=administrator.username,
        remote_addr="198.51.100.21",
    )

    _assert_throttled(nonexistent)
    _assert_throttled(existing)
    assert nonexistent.content == existing.content
    assert administrator.username.encode() not in existing.content
    assert b"task037b_does_not_exist" not in nonexistent.content


@pytest.mark.django_db
def test_distinct_direct_client_addresses_are_not_coupled():
    login_url = reverse("admin:login")
    first = Client()

    for _ in range(FAILURE_LIMIT - 1):
        _post_login(first, login_url, remote_addr="198.51.100.30")
    _assert_throttled(
        _post_login(first, login_url, remote_addr="198.51.100.30")
    )

    second = _post_login(
        Client(),
        login_url,
        remote_addr="198.51.100.31",
    )
    assert second.status_code == 200
    assert second.content != GENERIC_LOCKOUT_BODY


@pytest.mark.django_db
def test_local_http_ignores_spoofed_forwarded_addresses_and_still_throttles():
    client = Client()
    login_url = reverse("admin:login")

    page = client.get(
        login_url,
        secure=False,
        REMOTE_ADDR="198.51.100.40",
        HTTP_X_FORWARDED_FOR="203.0.113.1",
    )
    assert page.status_code == 200

    for suffix in range(1, FAILURE_LIMIT):
        response = _post_login(
            client,
            login_url,
            remote_addr="198.51.100.40",
            forwarded_for=f"203.0.113.{suffix}",
        )
        assert response.status_code == 200

    _assert_throttled(
        _post_login(
            client,
            login_url,
            remote_addr="198.51.100.40",
            forwarded_for="203.0.113.250",
        )
    )


@pytest.mark.django_db
def test_caddy_proxy_mode_distinguishes_forwarded_ipv4_and_ipv6_clients():
    login_url = reverse("admin:login")
    caddy_peer = "172.18.0.4"
    proxy_settings = {
        "BEHIND_HTTPS_PROXY": True,
        "AXES_IPWARE_META_PRECEDENCE_ORDER": (
            "HTTP_X_FORWARDED_FOR",
            "REMOTE_ADDR",
        ),
        "AXES_IPWARE_PROXY_ORDER": "left-most",
        "AXES_IPWARE_PROXY_COUNT": 0,
    }

    with override_settings(**proxy_settings):
        ipv4_client = Client()
        for _ in range(FAILURE_LIMIT - 1):
            _post_login(
                ipv4_client,
                login_url,
                remote_addr=caddy_peer,
                forwarded_for="198.51.100.50",
            )
        _assert_throttled(
            _post_login(
                ipv4_client,
                login_url,
                remote_addr=caddy_peer,
                forwarded_for="198.51.100.50",
            )
        )

        ipv6_response = _post_login(
            Client(),
            login_url,
            remote_addr=caddy_peer,
            forwarded_for="2001:db8::50",
        )

    assert ipv6_response.status_code == 200
    assert ipv6_response.content != GENERIC_LOCKOUT_BODY


@pytest.mark.django_db
def test_operator_can_reset_one_throttled_ip_and_restore_login(administrator):
    login_url = reverse("admin:login")
    client_ip = "198.51.100.60"
    client = Client()

    for _ in range(FAILURE_LIMIT - 1):
        _post_login(client, login_url, remote_addr=client_ip)
    _assert_throttled(_post_login(client, login_url, remote_addr=client_ip))

    call_command("axes_reset_ip", client_ip, verbosity=0)

    recovered = _post_login(
        Client(),
        login_url,
        username=administrator.username,
        password="task037b-test-password",
        remote_addr=client_ip,
    )
    assert recovered.status_code == 302
    assert recovered.headers["Location"] == "/admin/"


@pytest.mark.django_db
def test_authenticated_admin_and_authentication_boundaries_are_unchanged(
    client,
    administrator,
):
    client.force_login(administrator)
    assert client.get(reverse("admin:index")).status_code == 200

    client.logout()
    application_login = _post_login(
        client,
        reverse("login"),
        username=administrator.username,
        password="task037b-test-password",
        remote_addr="198.51.100.70",
    )
    assert application_login.status_code == 302
    assert application_login.headers["Location"] == "/admin/"

    assert Client().get("/auth/signup/").status_code == 404
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "rest_framework.authentication.SessionAuthentication"
    ]
