from paperless_pilot.application.events import Event, EventBus


async def test_subscribers_receive_events_until_they_leave() -> None:
    bus = EventBus()
    async with bus.subscribe() as first, bus.subscribe() as second:
        assert bus.subscriber_count == 2
        bus.publish("jobs", document_id=3)
        assert await first.get() == Event(topic="jobs", document_id=3)
        assert await second.get() == Event(topic="jobs", document_id=3)
    assert bus.subscriber_count == 0
    bus.publish("jobs")  # ohne Abonnenten kein Fehler


async def test_slow_subscriber_loses_oldest_events() -> None:
    bus = EventBus()
    async with bus.subscribe() as queue:
        for i in range(150):
            bus.publish("suggestions", document_id=i)
        assert queue.qsize() == 100
        assert (await queue.get()).document_id == 50
