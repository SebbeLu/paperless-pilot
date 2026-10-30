import logging

import uvicorn

from paperless_pilot.config import Settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()  # Pflichtwerte kommen aus der Umgebung
    uvicorn.run(
        "paperless_pilot.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
