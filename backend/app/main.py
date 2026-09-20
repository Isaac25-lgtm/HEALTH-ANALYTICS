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
    yield


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
