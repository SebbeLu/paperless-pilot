"""Anwendungsfall: Taxonomie pflegen und mit Paperless abgleichen."""

from collections.abc import Awaitable, Callable, Iterator
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from paperless_pilot.adapters.db.repositories import TaxonomyRepository
from paperless_pilot.application.events import EventBus
from paperless_pilot.domain.clock import Clock
from paperless_pilot.domain.ports import DocumentRepository
from paperless_pilot.domain.taxonomy import Taxonomy, TaxonomyEntry

type Group = Literal["document_types", "persons", "areas", "status"]


class SyncStatus(StrEnum):
    LINKED = "linked"  # verknüpft und vorhanden
    LINK_BY_NAME = "link_by_name"  # gleichnamiges Objekt vorhanden, wird verknüpft
    MISSING = "missing"  # wird angelegt
    STALE = "stale"  # verknüpftes Objekt wurde in Paperless gelöscht


class SyncItem(BaseModel):
    group: Group
    name: str
    status: SyncStatus
    paperless_id: int | None
    paperless_name: str | None


class TaxonomyState(BaseModel):
    taxonomy: Taxonomy
    configured: bool
    sync: list[SyncItem]

    @property
    def in_sync(self) -> bool:
        return all(i.status == SyncStatus.LINKED for i in self.sync)


class TaxonomyService:
    def __init__(
        self,
        repository: TaxonomyRepository,
        paperless: DocumentRepository,
        clock: Clock,
        events: EventBus,
    ) -> None:
        self._repository = repository
        self._paperless = paperless
        self._clock = clock
        self._events = events

    async def get(self) -> Taxonomy:
        taxonomy, _ = await self._repository.get()
        return taxonomy

    async def state(self) -> TaxonomyState:
        taxonomy, configured = await self._repository.get()
        return TaxonomyState(
            taxonomy=taxonomy, configured=configured, sync=await self._plan(taxonomy)
        )

    async def save(self, taxonomy: Taxonomy) -> TaxonomyState:
        await self._repository.save(taxonomy, self._clock.now())
        self._events.publish("taxonomy")
        return await self.state()

    async def apply_sync(self) -> TaxonomyState:
        """Verknüpft gleichnamige Objekte und legt fehlende in Paperless an."""
        taxonomy = await self.get()
        types = {t.name.casefold(): t.id for t in await self._paperless.list_document_types()}
        tags = {t.name.casefold(): t.id for t in await self._paperless.list_tags()}
        plan = {(i.group, i.name): i for i in await self._plan(taxonomy)}

        for group, entry in _entries(taxonomy):
            item = plan[(group, entry.name)]
            if item.status == SyncStatus.LINKED:
                continue
            known = types if group == "document_types" else tags
            create: Callable[[str], Awaitable[int]] = (
                self._create_type if group == "document_types" else self._create_tag
            )
            entry.paperless_id = known.get(entry.name.casefold()) or await create(entry.name)
        return await self.save(taxonomy)

    async def _create_type(self, name: str) -> int:
        return (await self._paperless.create_document_type(name)).id

    async def _create_tag(self, name: str) -> int:
        return (await self._paperless.create_tag(name)).id

    async def _plan(self, taxonomy: Taxonomy) -> list[SyncItem]:
        types = {t.id: t.name for t in await self._paperless.list_document_types()}
        tags = {t.id: t.name for t in await self._paperless.list_tags()}
        items = []
        for group, entry in _entries(taxonomy):
            existing = types if group == "document_types" else tags
            items.append(_sync_item(group, entry, existing))
        return items


def _entries(taxonomy: Taxonomy) -> Iterator[tuple[Group, TaxonomyEntry]]:
    for entry in taxonomy.document_types:
        yield "document_types", entry
    for person in taxonomy.persons:
        yield "persons", person
    for area in taxonomy.areas:
        yield "areas", area
    status = taxonomy.status
    for entry in (status.todo, status.review, status.done, status.error):
        yield "status", entry


def _sync_item(group: Group, entry: TaxonomyEntry, existing: dict[int, str]) -> SyncItem:
    by_name = {name.casefold(): pid for pid, name in existing.items()}
    if entry.paperless_id is not None and entry.paperless_id in existing:
        status, pid = SyncStatus.LINKED, entry.paperless_id
    elif entry.name.casefold() in by_name:
        status, pid = SyncStatus.LINK_BY_NAME, by_name[entry.name.casefold()]
    elif entry.paperless_id is not None:
        status, pid = SyncStatus.STALE, None
    else:
        status, pid = SyncStatus.MISSING, None
    return SyncItem(
        group=group,
        name=entry.name,
        status=status,
        paperless_id=pid,
        paperless_name=existing.get(pid) if pid is not None else None,
    )
