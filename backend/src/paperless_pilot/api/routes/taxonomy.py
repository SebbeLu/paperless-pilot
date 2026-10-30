from fastapi import APIRouter
from fastapi.responses import JSONResponse

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.taxonomy import TaxonomyState
from paperless_pilot.domain.taxonomy import Taxonomy

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("")
async def get_taxonomy(container: ContainerDep) -> TaxonomyState:
    """Taxonomie samt Abgleich mit Paperless."""
    return await container.taxonomy.state()


@router.put("")
async def save_taxonomy(taxonomy: Taxonomy, container: ContainerDep) -> TaxonomyState:
    """Speichert die Taxonomie (auch für den Import einer Sicherung)."""
    return await container.taxonomy.save(taxonomy)


@router.post("/sync")
async def sync_taxonomy(container: ContainerDep) -> TaxonomyState:
    """Verknüpft gleichnamige Objekte und legt fehlende in Paperless an."""
    return await container.taxonomy.apply_sync()


@router.get("/export", response_model=Taxonomy)
async def export_taxonomy(container: ContainerDep) -> JSONResponse:
    """Sicherung als JSON-Datei."""
    taxonomy = await container.taxonomy.get()
    return JSONResponse(
        taxonomy.model_dump(mode="json"),
        headers={"Content-Disposition": 'attachment; filename="paperless-pilot-taxonomie.json"'},
    )
