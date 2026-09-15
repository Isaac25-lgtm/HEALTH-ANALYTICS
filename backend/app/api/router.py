from fastapi import APIRouter

from app.api.routes import (
    admin,
    ai,
    analysis_snapshots,
    auth,
    calculations,
    dashboard,
    exports,
    health,
    indicators,
    mappings,
    me,
    modules,
    mpdsr,
    ops,
    org_units,
    populations,
    programmes,
    quality,
    search,
    sync,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(org_units.router)
api_router.include_router(programmes.router)
api_router.include_router(populations.router)
api_router.include_router(indicators.router)
api_router.include_router(calculations.router)
api_router.include_router(modules.router)
api_router.include_router(dashboard.router)
api_router.include_router(analysis_snapshots.router)
api_router.include_router(quality.router)
api_router.include_router(sync.router)
api_router.include_router(mappings.router)
api_router.include_router(exports.router)
api_router.include_router(ai.router)
api_router.include_router(ops.router)
api_router.include_router(mpdsr.router)
api_router.include_router(admin.router)
api_router.include_router(search.router)
