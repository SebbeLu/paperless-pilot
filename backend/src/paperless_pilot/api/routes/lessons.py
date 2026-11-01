from fastapi import APIRouter, status

from paperless_pilot.api.deps import ContainerDep
from paperless_pilot.domain.lessons import Lesson

router = APIRouter(prefix="/lessons", tags=["lessons"])


@router.get("")
async def list_lessons(container: ContainerDep) -> list[Lesson]:
    """Gelernte Korrekturen, die das Modell bei ähnlichen Dokumenten als Beispiel bekommt."""
    return await container.lessons.list()


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_lesson(lesson_id: int, container: ContainerDep) -> None:
    """Korrektur vergessen – sie wird nicht mehr als Beispiel verwendet."""
    await container.lessons.forget(lesson_id)
