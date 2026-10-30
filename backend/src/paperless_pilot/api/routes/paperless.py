from fastapi import APIRouter
from pydantic import BaseModel

from paperless_pilot.api.deps import ContainerDep

router = APIRouter(prefix="/paperless", tags=["paperless"])


class Option(BaseModel):
    id: int
    name: str


class CorrespondentOption(Option):
    excluded: bool


class Lookups(BaseModel):
    """Auswahllisten für die Oberfläche."""

    correspondents: list[CorrespondentOption]
    document_types: list[Option]
    tags: list[Option]


@router.get("/lookups")
async def lookups(container: ContainerDep) -> Lookups:
    paperless = container.adapters.paperless
    taxonomy = await container.taxonomy.get()
    return Lookups(
        correspondents=sorted(
            (
                CorrespondentOption(
                    id=c.id, name=c.name, excluded=taxonomy.is_excluded_correspondent(c.name)
                )
                for c in await paperless.list_correspondents()
            ),
            key=lambda c: c.name.casefold(),
        ),
        document_types=[
            Option(id=t.id, name=t.name) for t in await paperless.list_document_types()
        ],
        tags=[Option(id=t.id, name=t.name) for t in await paperless.list_tags()],
    )
