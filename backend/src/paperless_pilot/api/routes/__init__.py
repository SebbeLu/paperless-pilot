from fastapi import APIRouter

from paperless_pilot.api.routes import events, hosts, jobs, paperless, system, taxonomy

router = APIRouter()
for module in (system, taxonomy, paperless, hosts, jobs, events):
    router.include_router(module.router)
