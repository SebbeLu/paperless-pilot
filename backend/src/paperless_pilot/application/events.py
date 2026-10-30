"""Ereignisse für die Oberfläche (Server-Sent Events): leichtgewichtiges Publish/Subscribe."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel

type Topic = Literal["jobs", "suggestions", "changes", "hosts", "taxonomy"]

_QUEUE_SIZE = 100


class Event(BaseModel):
    topic: Topic
    document_id: int | None = None


class EventBus:
    """Je Abonnent eine Warteschlange; langsame Abonnenten verlieren die ältesten Ereignisse."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def publish(self, topic: Topic, document_id: int | None = None) -> None:
        event = Event(topic=topic, document_id=document_id)
        for queue in self._subscribers:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
