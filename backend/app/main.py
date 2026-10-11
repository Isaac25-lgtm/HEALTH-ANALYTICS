from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.csrf import CsrfMiddleware
from app.api.router import api_router
from app.api.security import SecurityHeadersMiddleware, cors_origins
from app.config import get_settings, validate_runtime_settings
from app.domain.formula_spec import FormulaValidationError
from app.domain.periods import PeriodError
from app.version import PHASE, SOFTWARE_VERSION

settings = get_settings()


def startup_configuration_errors() -> list[str]:
    """Blocking errors that stop a staging/production API from starting at all."""
    current = get_settings()
    return validate_runtime_settings(current) if current.is_production else []


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    errors = startup_configuration_errors()
    if errors:
        # Names of settings only; values are never echoed.
        raise RuntimeError("Refusing to start with blocking configuration errors: " + " ".join(errors))
    _start_background_preparation()
    yield


def _start_background_preparation() -> None:
    """Have maps and common views ready before the first person asks for them.

    Boundary shapes are simplified in this process (they are served from its memory). Dashboards
    are prepared in a separate process so calculation never competes with requests; in queue mode
    the worker does that instead. Nothing here can stop the API from starting.
    """
    current = get_settings()
    if current.app_env == "test":
        return
    if current.sync_execution == "eager" and current.dhis2_refresh_schedule_enabled:
        # No worker or Beat in eager mode: this process decides when the refresh script runs.
        from app.services.local_scheduler import scheduler

        scheduler.start()
    if not current.dashboard_precompute_enabled:
        return
    import subprocess
    import sys
    import threading
    from pathlib import Path

    def warm_boundaries() -> None:
        try:
            from app.services.geometry import warm_simplified_boundaries

            warm_simplified_boundaries()
        except Exception:  # noqa: BLE001 - a cold map is slower, never wrong
            pass

    threading.Thread(target=warm_boundaries, name="warm-boundaries", daemon=True).start()
    if current.sync_execution != "eager":
        return
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(  # noqa: S603 - fixed arguments, this interpreter
            [sys.executable, "-m", "scripts.prepare_dashboards", "--extended"],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError:
        pass


app = FastAPI(
    title=settings.app_name,
    version=SOFTWARE_VERSION,
    description=(
        "Corrective Phases 1–7: cookie sessions, deterministic calculation, MNCH modules, "
        "committed analytical snapshots, evidence-safe AI, and snapshot-bound publishing. "
        "DHIS2-backed sign-in and read-only metadata discovery are live; aggregate "
        "extraction awaits approved organisation-unit and source mappings. Official MoH "
        "templates remain pending owner inputs."
    ),
    lifespan=lifespan,
)

app.add_middleware(CsrfMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*", "X-CSRF-Token"],
)

app.include_router(api_router)


@app.exception_handler(PeriodError)
async def period_handler(_request: Request, exc: PeriodError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "invalid_period", "message": str(exc)},
    )


@app.exception_handler(FormulaValidationError)
async def formula_handler(_request: Request, exc: FormulaValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "invalid_formula", "message": str(exc)},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "database_error", "message": "Database is unavailable."},
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "hpip-api",
        "phase": PHASE,
        "docs": "/docs",
        "health": "/health",
    }
