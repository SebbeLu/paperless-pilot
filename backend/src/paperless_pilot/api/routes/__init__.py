from fastapi import APIRouter

from paperless_pilot.api.routes import (
    changes,
    documents,
    events,
    hosts,
    jobs,
    paperless,
    suggestions,
    system,
    taxonomy,
)

router = APIRouter()
for module in (
    system,
    taxonomy,
    paperless,
    hosts,
    jobs,
    suggestions,
    changes,
    documents,
    events,
):
    router.include_router(module.router)
