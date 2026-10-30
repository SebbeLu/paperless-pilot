from fastapi import APIRouter

from paperless_pilot.api.routes import paperless, system, taxonomy

router = APIRouter()
for module in (system, taxonomy, paperless):
    router.include_router(module.router)
