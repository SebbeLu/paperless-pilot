"""Anwendungsfall: Wie geht es Paperless und den Ollama-Rechnern gerade?"""

import asyncio
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from paperless_pilot.domain.errors import AuthenticationError, PilotError
from paperless_pilot.domain.ports import DocumentRepository, LlmHost

# Art des Problems, damit die Oberfläche passende Hinweise geben kann.
type Problem = Literal["unreachable", "auth"]


def _problem(error: PilotError) -> Problem:
    return "auth" if isinstance(error, AuthenticationError) else "unreachable"


class PaperlessStatus(BaseModel):
    reachable: bool
    version: str | None = None
    documents_total: int | None = None
    documents_inbox: int | None = None
    problem: Problem | None = None
    error: str | None = None


class HostStatus(BaseModel):
    name: str
    url: str
    reachable: bool
    version: str | None = None
    models: list[str] = []
    problem: Problem | None = None
    error: str | None = None


class SystemStatus(BaseModel):
    paperless: PaperlessStatus
    hosts: list[HostStatus]


class SystemStatusService:
    def __init__(self, paperless: DocumentRepository, hosts: Sequence[LlmHost]) -> None:
        self._paperless = paperless
        self._hosts = hosts

    async def get_status(self) -> SystemStatus:
        async with asyncio.TaskGroup() as tasks:
            paperless = tasks.create_task(self._paperless_status())
            hosts = [tasks.create_task(self._host_status(h)) for h in self._hosts]
        return SystemStatus(paperless=paperless.result(), hosts=[h.result() for h in hosts])

    async def _paperless_status(self) -> PaperlessStatus:
        try:
            info = await self._paperless.server_info()
        except PilotError as exc:
            return PaperlessStatus(reachable=False, problem=_problem(exc), error=str(exc))
        return PaperlessStatus(
            reachable=True,
            version=info.version,
            documents_total=info.documents_total,
            documents_inbox=info.documents_inbox,
        )

    @staticmethod
    async def _host_status(host: LlmHost) -> HostStatus:
        try:
            probe = await host.probe()
        except PilotError as exc:
            return HostStatus(
                name=host.name,
                url=host.base_url,
                reachable=False,
                problem=_problem(exc),
                error=str(exc),
            )
        return HostStatus(
            name=host.name,
            url=host.base_url,
            reachable=True,
            version=probe.version,
            models=sorted(m.name for m in probe.models),
        )
