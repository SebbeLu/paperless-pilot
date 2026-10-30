import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.application.events import EventBus

router = APIRouter(tags=["events"])

KEEPALIVE_SECONDS = 15.0


async def stream(bus: EventBus, keepalive: float = KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    async with bus.subscribe() as queue:
        yield ": verbunden\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: {event.topic}\ndata: {event.model_dump_json()}\n\n"


@router.get("/events", response_class=StreamingResponse)
async def events(container: ContainerDep) -> StreamingResponse:
    """Server-Sent Events: die Oberfläche lädt betroffene Daten neu."""
    return StreamingResponse(
        stream(container.events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
