"""Frozen TASK_034 production application runtime tests.

TASK_034 owns only the production application runtime: Gunicorn replaces
`runserver` as the web service's command, a one-shot `migrate` release
service gains ownership of applying migrations, explicit restart policies are
set, and a narrow, off-by-default production-security settings contract is
introduced. See tasks/TASK_034_PRODUCTION_APPLICATION_RUNTIME.md and
docs/09_PLANNING.md §9.

Ingress (Caddy, TLS termination, removing the published host port) is
TASK_035's job. This module deliberately does not assume Caddy, a real
domain, or a certificate exist — the web service's port stays published and
plain HTTP so TASK_034 remains independently testable.

The proxy-trust boundary is checked at BOTH layers a forwarded-proto header
passes through before Django ever sees it: Gunicorn's own
`forwarded_allow_ips` (explicitly pinned to the loopback-only allowlist) and
Django's `SECURE_PROXY_SSL_HEADER` (gated behind
`DJANGO_BEHIND_HTTPS_PROXY`, off by default). See
tasks/TASK_034_PRODUCTION_APPLICATION_RUNTIME.md §5.1 for the empirical,
non-pytest evidence (a real Docker NAT experiment) that no request arriving
through this repository's published-port topology can present a peer address
the explicit allowlist trusts; the live subprocess test in this module proves
the configured mechanism itself works, not that specific network fact.

Imports of `config.settings` as a reloadable module follow the pattern
established by tests/test_task_001_bootstrap.py. The settings-contract tests
resolve settings through `django.conf.Settings("config.settings")` rather
than asserting raw module attributes for the four gated names — those names
are only conditionally defined in `config/settings.py` (see §6 of the task
file), so asserting `settings_module.SECURE_SSL_REDIRECT is False` directly
would raise AttributeError against a correct implementation. Resolving
through Django's own settings loader gives the real, effective value
(Django's global default when the module doesn't override it), which is the
property that actually matters.
"""

import http.client
import importlib
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from django.conf import Settings as DjangoSettings
from django.test import RequestFactory, override_settings

REPO_ROOT = Path(__file__).resolve().parent.parent

_CONDITIONAL_SECURITY_SETTINGS = (
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
)


def _compose():
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def _web_service():
    return _compose()["services"]["web"]


def _db_service():
    return _compose()["services"]["db"]


# ---------------------------------------------------------------------------
# Gunicorn is the web runtime, not runserver
# ---------------------------------------------------------------------------


def test_requirements_declares_a_pinned_gunicorn_dependency():
    """requirements.txt adds gunicorn pinned to a next-major ceiling, like psycopg."""
    lines = (REPO_ROOT / "requirements.txt").read_text().splitlines()
    gunicorn_lines = [line for line in lines if line.lower().startswith("gunicorn")]
    assert gunicorn_lines, "requirements.txt must declare a gunicorn dependency"
    assert len(gunicorn_lines) == 1
    assert gunicorn_lines[0] == "gunicorn>=26.0.0,<27", gunicorn_lines[0]


def test_no_runserver_anywhere_in_compose_or_docker_files():
    """runserver must not remain the production web command anywhere in the release."""
    for relative in ("docker-compose.yml", "Dockerfile", "docker-entrypoint.sh"):
        text = (REPO_ROOT / relative).read_text()
        assert "runserver" not in text, f"{relative} still references runserver"


def test_web_service_command_runs_gunicorn_against_the_django_wsgi_module():
    web = _web_service()
    command = web["command"]
    assert "gunicorn" in command
    assert "config.wsgi:application" in command
    assert "0.0.0.0:8000" in command
    assert "runserver" not in command


def test_web_service_command_does_not_pin_a_worker_or_thread_count():
    """No CPU/RAM assumption is invented; gunicorn's own WEB_CONCURRENCY/default-1
    mechanism is deferred to until a real host exists (TASK_038)."""
    command = _web_service()["command"]
    assert "--workers" not in command
    assert "--threads" not in command


def test_web_service_still_publishes_its_host_port():
    """TASK_034 only swaps what serves the port; removing the published port
    is TASK_035's ingress cutover, not this task's."""
    assert "8000:8000" in _web_service()["ports"]


def test_gunicorn_resolves_the_configured_django_wsgi_application():
    """A stronger-than-YAML-parsing check: once gunicorn is actually installed,
    it must be able to load config.wsgi:application without error."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "gunicorn", "--check-config", "config.wsgi:application"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        pytest.fail("gunicorn is not installed; TASK_034 must add it to requirements.txt")
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Gunicorn's own forwarded-header trust (the layer below Django's —
# task file §5.1)
# ---------------------------------------------------------------------------


def test_web_command_explicitly_limits_gunicorns_forwarded_header_trust_to_loopback():
    """The safe allowlist is repository-controlled rather than inherited from
    a package default or an operator-supplied FORWARDED_ALLOW_IPS value.
    Wildcard trust remains forbidden while the port is directly published
    (task file §5.1, §2.1)."""
    command = _web_service()["command"]
    assert command.split().count("--forwarded-allow-ips=127.0.0.1,::1") == 1
    assert "--forwarded-allow-ips=*" not in command
    assert "FORWARDED_ALLOW_IPS" not in command
    assert "secure-scheme-headers" not in command


def _free_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_gunicorns_explicit_forwarded_header_trust_actually_works_from_a_trusted_peer(
    tmp_path,
):
    """Live-process, loopback-only proof (no external network) that gunicorn's
    explicit allowlist gates `X-Forwarded-Proto` on the peer address, by
    exercising the real mechanism rather than reimplementing it. A request
    from the configured 127.0.0.1 peer must have its forwarded header honored.
    The separate, environment-specific fact that this repository's actual
    published-port topology never presents a peer address the allowlist would
    trust is empirical evidence recorded in the task file
    (§5.1), not something a hermetic test running on arbitrary infrastructure
    can assert as a general property of "127.0.0.1,::1"."""
    probe_app = tmp_path / "forwarded_proto_probe.py"
    probe_app.write_text(
        "def application(environ, start_response):\n"
        "    body = environ.get('wsgi.url_scheme', '').encode()\n"
        "    start_response('200 OK', "
        "[('Content-Type', 'text/plain'), ('Content-Length', str(len(body)))])\n"
        "    return [body]\n"
    )
    port = _free_loopback_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "gunicorn",
            "--bind", f"127.0.0.1:{port}",
            "--forwarded-allow-ips=127.0.0.1,::1",
            "--workers", "1",
            "--chdir", str(tmp_path),
            "forwarded_proto_probe:application",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    scheme = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(
                    "gunicorn is not installed; TASK_034 must add it to "
                    f"requirements.txt (process exited early: {proc.stdout.read() if proc.stdout else ''})"
                )
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                conn.request("GET", "/", headers={"X-Forwarded-Proto": "https"})
                response = conn.getresponse()
                scheme = response.read().decode()
                conn.close()
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.2)
        else:
            pytest.fail("gunicorn never became reachable on 127.0.0.1 within 10s")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    assert scheme == "https", (
        "gunicorn's explicit forwarded_allow_ips must treat the configured "
        f"loopback peer (127.0.0.1) as trusted — got scheme={scheme!r}"
    )


# ---------------------------------------------------------------------------
# Migration release mechanism
# ---------------------------------------------------------------------------


def test_migrate_service_exists_and_shares_the_application_image():
    compose = _compose()
    assert "migrate" in compose["services"], (
        "a one-shot migrate release service must exist so no migration races "
        "web startup or a future second web instance"
    )
    migrate = compose["services"]["migrate"]
    web = compose["services"]["web"]
    assert migrate.get("build") == web.get("build"), (
        "the migrate service must run the same application image as web, "
        "not a bespoke one"
    )


def test_migrate_service_command_applies_migrations_noninteractively():
    command = _compose()["services"]["migrate"]["command"]
    assert "migrate" in command
    assert "--noinput" in command


def test_migrate_service_does_not_restart():
    """A one-shot release step must not retry itself; a failed migration must
    surface as an inspectable, retained container (task file §7.2), not
    silently loop."""
    migrate = _compose()["services"]["migrate"]
    assert str(migrate.get("restart", "no")) == "no"


def test_migrate_service_waits_for_a_healthy_database():
    migrate_depends_on = _compose()["services"]["migrate"]["depends_on"]
    assert migrate_depends_on["db"]["condition"] == "service_healthy"


def test_web_service_does_not_start_until_migrate_completes_successfully():
    """The web container must not be created against an unapplied schema. A
    failed migrate run (nonzero exit) never satisfies this condition, so web
    never starts. An ordinary `docker compose restart web` does not re-enter
    this dependency chain (verified empirically, task file §7.2), so ordinary
    restarts create no second uncontrolled migration path."""
    web_depends_on = _web_service()["depends_on"]
    assert web_depends_on["migrate"]["condition"] == "service_completed_successfully"
    assert web_depends_on["db"]["condition"] == "service_healthy"


def test_no_new_migration_file_is_introduced():
    result = subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Restart policy
# ---------------------------------------------------------------------------


def test_web_service_restart_policy_is_unless_stopped():
    """unless-stopped restarts web after a crash or a container-engine/host
    restart, but keeps a deliberately-stopped web stopped across that same
    restart (unlike `always`, which would resurrect it) — task file §8."""
    assert _web_service().get("restart") == "unless-stopped"


def test_db_service_restart_policy_is_unless_stopped():
    """db must not be left at Compose's own default (`no`, never
    auto-restarts): a host/container-engine restart must not leave web
    auto-recovering while its database stays down, which would defeat the
    reason web has a restart policy at all — task file §8."""
    assert _db_service().get("restart") == "unless-stopped"


# ---------------------------------------------------------------------------
# Production security settings contract
# ---------------------------------------------------------------------------


def _reload_settings_module(settings_module):
    """Remove conditionally-defined names because reload retains a module's dict."""
    for setting_name in _CONDITIONAL_SECURITY_SETTINGS:
        settings_module.__dict__.pop(setting_name, None)
    return importlib.reload(settings_module)


@pytest.fixture
def settings_module(monkeypatch):
    from config import settings as settings_module

    yield settings_module
    # Undo the env patch *before* reloading, so the reload that restores this
    # fixture's own module state reflects the true pre-test environment
    # rather than whatever the last parametrized case set — otherwise a
    # later test importing the already-reloaded module fresh could observe
    # a stale value for the brief window before its own reload runs.
    monkeypatch.undo()
    _reload_settings_module(settings_module)


def _resolved_settings(settings_module):
    """A fully-resolved settings snapshot: Django's own global defaults
    overlaid with whatever config/settings.py's *current* module state
    explicitly defines — exactly what django.conf.LazySettings does at real
    startup. Works correctly whether the four gated settings are
    conditionally defined (present only when BEHIND_HTTPS_PROXY is True) or
    unconditionally defined with a ternary; either is a valid implementation
    of the task file §6 contract."""
    return DjangoSettings(settings_module.__name__)


def test_behind_https_proxy_flag_defaults_off_and_leaves_django_defaults(
    monkeypatch, settings_module
):
    """With no DJANGO_BEHIND_HTTPS_PROXY set — TASK_034's own deployed state,
    before TASK_035 puts a real proxy in front — every proxy/cookie/redirect
    setting must resolve to Django's own default, not a TASK_034 override."""
    monkeypatch.delenv("DJANGO_BEHIND_HTTPS_PROXY", raising=False)
    _reload_settings_module(settings_module)

    assert settings_module.BEHIND_HTTPS_PROXY is False

    resolved = _resolved_settings(settings_module)
    assert resolved.SECURE_PROXY_SSL_HEADER is None
    assert resolved.SECURE_SSL_REDIRECT is False
    assert resolved.SESSION_COOKIE_SECURE is False
    assert resolved.CSRF_COOKIE_SECURE is False


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "1 ", " 1", "on", ""])
def test_only_the_literal_string_one_enables_behind_https_proxy(
    monkeypatch, settings_module, value
):
    """Matches the ENABLE_DEMO_DATA / ENABLE_ALERTS convention: literal "1"
    only, no truthy-string heuristic, so enabling this requires a deliberate
    environment change."""
    monkeypatch.setenv("DJANGO_BEHIND_HTTPS_PROXY", value)
    _reload_settings_module(settings_module)

    assert settings_module.BEHIND_HTTPS_PROXY is False


def test_behind_https_proxy_flag_enables_the_full_proxy_and_cookie_contract(
    monkeypatch, settings_module
):
    """Once TASK_035 sets this to "1" against a real Caddy deployment that
    strips and re-sets X-Forwarded-Proto itself, all four settings must
    activate together — this is the mechanism TASK_035 flips, not one it has
    to (re)build."""
    monkeypatch.setenv("DJANGO_BEHIND_HTTPS_PROXY", "1")
    _reload_settings_module(settings_module)

    assert settings_module.BEHIND_HTTPS_PROXY is True

    resolved = _resolved_settings(settings_module)
    assert resolved.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert resolved.SECURE_SSL_REDIRECT is True
    assert resolved.SESSION_COOKIE_SECURE is True
    assert resolved.CSRF_COOKIE_SECURE is True


def test_djangos_layer_cannot_be_spoofed_by_a_direct_client_while_flag_is_disabled():
    """The Django-layer half of the proxy-trust hazard this task must not
    create: with the web service's port directly published and no
    controlling proxy in front (TASK_034's own state), a request carrying a
    client-supplied X-Forwarded-Proto: https header over a plain HTTP
    connection must not be treated as secure. The Gunicorn-layer half is
    covered separately above and in the task file §5.1."""
    from django.conf import settings

    assert settings.SECURE_PROXY_SSL_HEADER is None, (
        "SECURE_PROXY_SSL_HEADER must stay unset in the default test/deploy "
        "configuration used by this process"
    )
    request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")
    assert request.is_secure() is False


def test_djangos_layer_trusts_forwarded_proto_once_the_setting_is_enabled():
    """Proves Django's own mechanism is correct, so TASK_035 only needs to
    flip DJANGO_BEHIND_HTTPS_PROXY rather than reopen this task's security
    model."""
    with override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
        secure_request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")
        assert secure_request.is_secure() is True

        insecure_request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="http")
        assert insecure_request.is_secure() is False

        no_header_request = RequestFactory().get("/")
        assert no_header_request.is_secure() is False


def test_csrf_trusted_origins_is_not_introduced():
    """The application is same-origin (React + Django session/CSRF, TASK_026).
    Django's CSRF protection compares the Origin header against the request's
    own scheme+host; CSRF_TRUSTED_ORIGINS exists for cross-origin deployments
    this repository does not have. Freezing it here would be checklist
    theatre, not a real requirement."""
    from django.conf import settings

    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    assert "CSRF_TRUSTED_ORIGINS" not in settings_source
    assert settings.CSRF_TRUSTED_ORIGINS == []


def test_hsts_is_not_configured_by_task_034():
    """HSTS is browser-cached and irreversible-in-practice if misapplied
    before TLS is live and verified. TASK_034 adds the mechanism the other
    settings need; it deliberately does not pick an HSTS duration, because no
    duration has authority behind it yet and no TLS exists yet to make one
    safe. That decision belongs to TASK_035/038 once a real certificate is
    verified."""
    from django.conf import settings

    settings_source = (REPO_ROOT / "config" / "settings.py").read_text()
    assert "SECURE_HSTS_SECONDS" not in settings_source
    assert settings.SECURE_HSTS_SECONDS == 0


# ---------------------------------------------------------------------------
# Environment/.env.example symmetry (TASK_001's frozen test already enforces
# the general bidirectional rule; this pins the specific new key so a typo in
# either file is caught precisely rather than only generically).
# ---------------------------------------------------------------------------


def test_env_example_documents_the_new_proxy_flag_disabled_by_default():
    env_text = (REPO_ROOT / ".env.example").read_text()
    matching = [
        line for line in env_text.splitlines()
        if line.strip().startswith("DJANGO_BEHIND_HTTPS_PROXY=")
    ]
    assert matching, ".env.example must document DJANGO_BEHIND_HTTPS_PROXY"
    assert matching[0].strip() == "DJANGO_BEHIND_HTTPS_PROXY=0", (
        "the example value must ship disabled so local/current compose usage "
        "needs no domain or proxy to keep working"
    )


# ---------------------------------------------------------------------------
# Compatibility: settled contracts this task must not disturb
# ---------------------------------------------------------------------------


def test_whitenoise_static_serving_contract_is_undisturbed():
    """Light re-check, not a re-test of TASK_026's full collectstatic flow:
    TASK_034 must not reorder middleware or change the staticfiles backend
    while introducing gunicorn."""
    from django.conf import settings

    security_index = settings.MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
    whitenoise_index = settings.MIDDLEWARE.index("whitenoise.middleware.WhiteNoiseMiddleware")
    assert whitenoise_index == security_index + 1
    assert (
        settings.STORAGES["staticfiles"]["BACKEND"]
        == "whitenoise.storage.CompressedStaticFilesStorage"
    )


def test_database_engine_is_still_postgresql_only():
    from django.conf import settings

    for alias, config in settings.DATABASES.items():
        assert "sqlite" not in config["ENGINE"].lower(), alias
        assert config["ENGINE"] == "django.db.backends.postgresql"
