"""Fehler, die Adapter an den Kern melden. Der Kern kennt keine HTTP- oder Bibliotheksfehler."""


class PilotError(Exception):
    """Basis aller fachlich behandelbaren Fehler."""


class ServiceUnavailableError(PilotError):
    """Ein externer Dienst (Paperless, Ollama-Rechner) ist nicht erreichbar oder fehlerhaft."""

    def __init__(self, service: str, detail: str) -> None:
        super().__init__(f"{service} nicht erreichbar: {detail}")
        self.service = service
        self.detail = detail


class AuthenticationError(PilotError):
    """Zugangsdaten fehlen, sind ungültig oder haben nicht die nötigen Rechte."""


class NotFoundError(PilotError):
    """Das angefragte Objekt (Dokument, Modell …) existiert nicht."""


class InvalidLlmOutputError(PilotError):
    """Die Modellantwort passt nicht zum verlangten Schema."""

    def __init__(self, model: str, raw_output: str, detail: str) -> None:
        super().__init__(f"Antwort von {model} passt nicht zum Schema: {detail}")
        self.model = model
        self.raw_output = raw_output
