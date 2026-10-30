from typing import Annotated

from fastapi import Depends, Request

from paperless_pilot.api.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
