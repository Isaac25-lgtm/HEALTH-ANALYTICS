"""Static checks of the container and compose configuration.

Docker is not required: compose files are parsed as YAML, ``${VAR:?message}`` / ``${VAR:-default}``
interpolation is resolved here, and the resulting backend environment is passed through the
application's own fail-closed validation. CI additionally runs ``docker compose config`` and a
containerised queue smoke test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings, validate_runtime_settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DEV_COMPOSE = ROOT / "docker-compose.dev.yml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
PRODUCTION_TEMPLATE = ROOT / ".env.production.example"
VARIABLE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?:(?P<op>:\?|:-)(?P<arg>[^}]*))?\}")


class MissingVariable(KeyError):
    pass


def _interpolate(value, env: dict[str, str]):
    if isinstance(value, dict):
        return {key: _interpolate(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, env) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match) -> str:
        name, op, arg = match.group("name"), match.group("op"), match.group("arg")
        current = env.get(name, "")
        if op == ":?" and not current:
            raise MissingVariable(name)
        if op == ":-" and not current:
            return arg
        return current

    return VARIABLE.sub(replace, value.replace("$$", "\0")).replace("\0", "$")


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _required_variables(text: str) -> set[str]:
    return {match.group("name") for match in VARIABLE.finditer(text) if match.group("op") == ":?"}


def _full_env() -> dict[str, str]:
    return {
        "POSTGRES_USER": "owner_user",
        "POSTGRES_PASSWORD": "owner-generated-postgres-secret",
        "POSTGRES_DB": "hpip",
        "REDIS_PASSWORD": "owner-generated-redis-secret",
        "AUTH_SECRET": "owner-generated-auth-secret-with-plenty-of-entropy",
        "SEED_PASSWORD": "owner-generated-unused-seed-password",
        "WEB_ORIGIN": "https://hpip.example.test",
        "ALLOWED_ORIGINS": "https://hpip.example.test",
        "ALLOWED_HOSTS": "hpip.example.test,localhost",
        "HEALTHCHECK_HOST": "localhost",
    }


def test_compose_defines_the_full_stack_with_healthchecks_and_ordering():
    services = _compose()["services"]
    assert set(services) == {"postgres", "redis", "migrate", "api", "worker", "web"}
    for name in ("postgres", "redis", "api", "worker", "web"):
        assert services[name].get("healthcheck", {}).get("test"), f"{name} has no healthcheck"
    for name in ("api", "worker"):
        depends = services[name]["depends_on"]
        assert depends["postgres"]["condition"] == "service_healthy"
        assert depends["redis"]["condition"] == "service_healthy"
        assert depends["migrate"]["condition"] == "service_completed_successfully"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    worker = " ".join(services["worker"]["command"])
    assert "celery" in worker and " worker" in worker and "exports" in _interpolate(worker, {})
    assert "inspect ping" in " ".join(services["worker"]["healthcheck"]["test"])
    assert services["api"]["volumes"] == services["worker"]["volumes"]


def test_compose_has_no_usable_default_credentials():
    text = COMPOSE.read_text(encoding="utf-8")
    for forbidden in ("change-me", "changeme", "dev-only", "password123", "hpip:hpip"):
        assert forbidden not in text.lower()
    required = _required_variables(text)
    assert {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "REDIS_PASSWORD",
        "AUTH_SECRET",
        "WEB_ORIGIN",
        "ALLOWED_HOSTS",
    } <= required
    with pytest.raises(MissingVariable):
        _interpolate(_compose(), {})
    for name in required:
        env = _full_env()
        env.pop(name, None)
        with pytest.raises(MissingVariable):
            _interpolate(_compose(), env)
    template = PRODUCTION_TEMPLATE.read_text(encoding="utf-8")
    for name in required:
        assert re.search(rf"^#?\s*{name}=\s*$", template, re.MULTILINE), f"{name} missing from template"


def test_browser_never_needs_the_backend_hostname():
    """The web service proxies /api server-side, so cookies stay on the frontend origin."""
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    web = services["web"]
    assert "args" not in web.get("build", {}), "no API origin is baked into the image"
    assert web["environment"]["BACKEND_INTERNAL_URL"] == "http://api:8000"
    assert set(web["networks"]) == {"frontend", "backend"}
    # The proxy is a runtime route handler: no build-time rewrite can capture a backend address.
    next_config = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    assert "async rewrites(" not in next_config
    route = (ROOT / "frontend" / "src" / "app" / "api" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    assert "proxyRequest" in route and 'dynamic = "force-dynamic"' in route
    proxy = (ROOT / "frontend" / "src" / "lib" / "server" / "proxy.ts").read_text(encoding="utf-8")
    assert "BACKEND_INTERNAL_URL" in proxy and "getSetCookie" in proxy
    api_client = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert 'const API_BASE = "/api";' in api_client
    assert "NEXT_PUBLIC_API_BASE_URL" not in api_client
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG NEXT_PUBLIC_API_BASE_URL" not in dockerfile
    assert "ENV BACKEND_INTERNAL_URL" not in dockerfile, "the proxy target is runtime-only, with no silent default"


def test_compose_configures_a_small_connection_budget_and_private_network_tls_choice():
    environment = _interpolate(_compose(), _full_env())["services"]["api"]["environment"]
    assert environment["DB_REQUIRE_SSL"] == "false"  # private compose network, stated explicitly
    assert int(environment["DB_POOL_SIZE"]) + int(environment["DB_MAX_OVERFLOW"]) <= 20


def test_redis_requires_a_password_and_urls_carry_it():
    services = _interpolate(_compose(), _full_env())["services"]
    assert "--requirepass" in " ".join(services["redis"]["command"])
    env = services["api"]["environment"]
    for key in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        assert env[key].startswith("redis://:owner-generated-redis-secret@redis:6379/")


def test_compose_backend_environment_passes_production_validation():
    services = _interpolate(_compose(), _full_env())["services"]
    for name in ("api", "worker", "migrate"):
        env = services[name]["environment"]
        assert env["APP_ENV"] == "production"
        assert env["EXPORT_EAGER"] == "false"
        assert env["RATE_LIMIT_BACKEND"] == "redis"
        assert env["SYNC_EXECUTION"] == "queue"
        assert env["AUTH_COOKIE_SECURE"] == "true"
        assert env["SEED_DEV_DATA"] == "false"
        settings = Settings(_env_file=None, **{key.lower(): value for key, value in env.items()})
        assert validate_runtime_settings(settings) == [], name
        assert settings.is_production and settings.export_eager is False


def test_dev_compose_is_explicitly_development_only():
    services = yaml.safe_load(DEV_COMPOSE.read_text(encoding="utf-8"))["services"]
    api = services["api"]["environment"]
    assert api["APP_ENV"] == "development"
    assert api["EXPORT_EAGER"] == "true" and api["RATE_LIMIT_BACKEND"] == "memory"
    for service in services.values():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:")


def test_backend_image_installs_worker_dependencies_and_runs_unprivileged():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'pip install ".[worker]"' in text
    assert "README.md" not in text  # the backend has no README; copying one broke the build
    assert re.search(r"^USER hpip$", text, re.MULTILINE)
    assert "HEALTHCHECK" in text and "scripts/healthcheck.py" in text
    assert "EXPORT_EAGER=false" in text and "RATE_LIMIT_BACKEND=redis" in text
    pyproject = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"worker = \[\s*\"celery\[redis\]", pyproject)


# ---------------------------------------------------------------------------
# Render blueprint (work packages Q, R, S)
# ---------------------------------------------------------------------------

RENDER = ROOT / "render.yaml"
BACKEND_SERVICES = ("hpip-api", "hpip-worker", "hpip-purge")
SECRET_KEYS = {"DATABASE_URL", "MIGRATION_DATABASE_URL", "AUTH_SECRET", "SEED_PASSWORD"}
DEPLOYMENT_SPECIFIC = {"WEB_ORIGIN", "ALLOWED_ORIGINS", "ALLOWED_HOSTS"}
# Every setting a backend process needs in production, whatever its role.
REQUIRED_BACKEND_SETTINGS = {
    "APP_ENV",
    "DATABASE_URL",
    "DB_SSLMODE",
    "DB_REQUIRE_SSL",
    "AUTH_SECRET",
    "SEED_PASSWORD",
    "SEED_DEV_DATA",
    "AUTH_COOKIE_SECURE",
    "WEB_ORIGIN",
    "ALLOWED_ORIGINS",
    "ALLOWED_HOSTS",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "RATE_LIMIT_BACKEND",
    "SYNC_EXECUTION",
    "EXPORT_EAGER",
    "EXPORT_ARTIFACT_STORAGE",
    "EXPORT_SHARED_FILESYSTEM",
    "RAW_AGGREGATE_RETENTION_DAYS",
    "MPDSR_EVENT_RETENTION_HOURS",
    "EXPORT_FILE_RETENTION_HOURS",
    "EXPORT_JOB_RETENTION_DAYS",
    "CALCULATION_SNAPSHOT_RETENTION_MONTHS",
    "AUDIT_LOG_RETENTION_MONTHS",
    "OPERATIONAL_RECORD_RETENTION_DAYS",
    "PURGE_ENABLED",
    "DHIS2_ENABLED",
    "SYNC_ENABLED",
    "AI_ENABLED",
}


def _render() -> dict:
    return yaml.safe_load(RENDER.read_text(encoding="utf-8"))


def _service(name: str) -> dict:
    return next(item for item in _render()["services"] if item["name"] == name)


def _groups() -> dict[str, list[dict]]:
    return {group["name"]: group["envVars"] for group in _render().get("envVarGroups", [])}


def _effective(service: dict) -> dict[str, dict]:
    """Every variable a service receives: its groups first, then its own declarations."""
    variables: dict[str, dict] = {}
    for item in service.get("envVars", []):
        if "fromGroup" in item:
            for grouped in _groups()[item["fromGroup"]]:
                variables[grouped["key"]] = grouped
    for item in service.get("envVars", []):
        if "key" in item:
            variables[item["key"]] = item
    return variables


def test_render_blueprint_is_a_small_one_worker_topology_with_a_private_api():
    blueprint = _render()
    names = {item["name"]: item["type"] for item in blueprint["services"]}
    assert names == {
        "hpip-redis": "keyvalue",
        "hpip-api": "pserv",
        "hpip-web": "web",
        "hpip-worker": "worker",
        "hpip-purge": "cron",
    }
    # Neon is external: no Render PostgreSQL. The inert DHIS2 refresh is not provisioned for UAT.
    assert blueprint.get("databases") == []
    assert "hpip-dhis2-refresh" not in names
    workers = [item for item in blueprint["services"] if item["type"] == "worker"]
    assert len(workers) == 1
    command = workers[0]["dockerCommand"]
    for queue in ("exports", "sync", "maintenance"):
        assert queue in command
    assert "celery" in command and "worker" in command
    # Only the web service is public.
    assert [item["name"] for item in blueprint["services"] if item["type"] == "web"] == ["hpip-web"]


def test_render_references_resolve_to_defined_groups_services_and_keys():
    blueprint = _render()
    services = {item["name"]: item for item in blueprint["services"]}
    groups = _groups()
    for service in blueprint["services"]:
        for item in service.get("envVars", []):
            if "fromGroup" in item:
                assert item["fromGroup"] in groups, f"{service['name']} uses undefined group {item['fromGroup']}"
                continue
            source = item.get("fromService")
            if not source:
                continue
            target = services.get(source["name"])
            assert target is not None, f"{service['name']}.{item['key']} references a missing service"
            assert target["type"] == source["type"], f"{service['name']}.{item['key']} has the wrong service type"
            if "envVarKey" in source:
                assert source["envVarKey"] in {
                    entry["key"] for entry in target.get("envVars", []) if "key" in entry
                }, f"{service['name']}.{item['key']} copies an undeclared key"
            else:
                assert source["property"] in {"host", "port", "hostport", "connectionString"}


def test_render_group_holds_no_secrets_and_no_sync_false():
    for name, variables in _groups().items():
        for item in variables:
            assert "sync" not in item, f"{name}.{item['key']}: Render groups cannot prompt for values"
            assert item["key"] not in SECRET_KEYS | DEPLOYMENT_SPECIFIC
            assert "generateValue" not in item


def test_render_contains_no_secret_values():
    text = RENDER.read_text(encoding="utf-8")
    for forbidden in ("password=", "postgres://", "postgresql://h", "redis://:", "sk-", "change-me"):
        assert forbidden not in text.lower()
    api = {item["key"]: item for item in _service("hpip-api")["envVars"] if "key" in item}
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", *DEPLOYMENT_SPECIFIC):
        assert api[key].get("sync") is False and "value" not in api[key], key
    for key in ("AUTH_SECRET", "SEED_PASSWORD"):
        assert api[key].get("generateValue") is True, key


def test_render_every_backend_process_receives_every_required_setting():
    for name in BACKEND_SERVICES:
        missing = REQUIRED_BACKEND_SETTINGS - set(_effective(_service(name)))
        assert missing == set(), f"{name} is missing {sorted(missing)}"


def test_render_secrets_are_declared_once_and_copied_identically():
    for name in ("hpip-worker", "hpip-purge"):
        variables = _effective(_service(name))
        for key in ("DATABASE_URL", "AUTH_SECRET", "SEED_PASSWORD", *DEPLOYMENT_SPECIFIC):
            source = variables[key].get("fromService")
            assert source == {"type": "pserv", "name": "hpip-api", "envVarKey": key}, (name, key)
            assert "value" not in variables[key] and "sync" not in variables[key]
        for key in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
            assert variables[key]["fromService"] == {
                "type": "keyvalue",
                "name": "hpip-redis",
                "property": "connectionString",
            }


def test_render_keys_are_real_settings():
    fields = set(Settings.model_fields)
    for name in BACKEND_SERVICES:
        unknown = {key for key in _effective(_service(name)) if key.lower() not in fields}
        assert unknown == set(), f"{name} sets unknown settings {sorted(unknown)}"


@pytest.mark.parametrize("name", BACKEND_SERVICES)
def test_render_backend_environment_passes_production_validation(name):
    """Resolve the blueprint as Render would, with owner-supplied stand-ins for the prompted values."""
    stand_ins = {
        "DATABASE_URL": "postgresql://hpip_app:owner-supplied@ep-example-pooler.neon.test/hpip?sslmode=require",
        "MIGRATION_DATABASE_URL": "postgresql://hpip_app:owner-supplied@ep-example.neon.test/hpip?sslmode=require",
        "AUTH_SECRET": "render-generated-auth-secret-with-plenty-of-entropy",
        "SEED_PASSWORD": "render-generated-unused-seed-password",
        "WEB_ORIGIN": "https://hpip-web.example.test",
        "ALLOWED_ORIGINS": "https://hpip-web.example.test",
        "ALLOWED_HOSTS": "hpip-api",
        "connectionString": "redis://red-example:6379",
    }
    environment: dict[str, str] = {}
    for key, item in _effective(_service(name)).items():
        if "value" in item:
            environment[key] = str(item["value"])
        elif "fromService" in item:
            source = item["fromService"]
            environment[key] = stand_ins[source.get("envVarKey") or source["property"]]
        else:
            environment[key] = stand_ins[key]
    settings = Settings(_env_file=None, **{key.lower(): value for key, value in environment.items()})
    assert validate_runtime_settings(settings) == []


def test_render_api_runs_migrations_then_the_reference_bootstrap():
    api = _service("hpip-api")
    assert api["preDeployCommand"] == "alembic upgrade head && python scripts/bootstrap_reference_data.py"
    assert "healthCheckPath" not in api  # private services have no public health check path
    values = _effective(api)
    assert values["DB_SSLMODE"]["value"] == "require"
    assert int(values["DB_POOL_SIZE"]["value"]) + int(values["DB_MAX_OVERFLOW"]["value"]) <= 20
    assert values["EXPORT_ARTIFACT_STORAGE"]["value"] == "database"
    assert values["EXPORT_SHARED_FILESYSTEM"]["value"] == "false"


def test_render_keeps_dhis2_and_ai_switched_off():
    values = _effective(_service("hpip-api"))
    assert values["DHIS2_ENABLED"]["value"] == "false"
    assert values["SYNC_ENABLED"]["value"] == "false"
    assert values["AI_ENABLED"]["value"] == "false"
    assert values["DHIS2_BASE_URL"]["value"] == "https://hmis.health.go.ug"
    for key in ("DHIS2_USERNAME", "DHIS2_PASSWORD", "DHIS2_PAT"):
        assert key not in values


def test_render_purge_job_uses_the_same_purge_service_and_retries():
    purge = _service("hpip-purge")
    assert purge["type"] == "cron"
    command = purge["dockerCommand"]
    assert "scripts/purge_expired.py" in command
    assert "--max-attempts 3" in command and "--source scheduler" in command
    assert purge["schedule"]


def test_render_web_service_proxies_to_the_private_api_at_runtime():
    web = _service("hpip-web")
    values = {item["key"]: item for item in web["envVars"]}
    assert values["BACKEND_INTERNAL_URL"]["fromService"] == {
        "type": "pserv",
        "name": "hpip-api",
        "property": "hostport",
    }
    assert "NEXT_PUBLIC_API_BASE_URL" not in values
    assert web["healthCheckPath"] == "/login"
