"""Demo-Modus: erfundene Dokumente und ein regelbasiertes „Modell“ statt Paperless und Ollama.

Dient zum Ausprobieren ohne eigene Infrastruktur, für Ende-zu-Ende-Tests und für Screenshots.
Alle Namen und Inhalte sind frei erfunden.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from paperless_pilot.domain.errors import NotFoundError
from paperless_pilot.domain.models import (
    Correspondent,
    Document,
    DocumentFile,
    DocumentPatch,
    DocumentType,
    FileKind,
    HostProbe,
    LlmModel,
    PaperlessInfo,
    Tag,
)
from paperless_pilot.domain.taxonomy import Taxonomy

if TYPE_CHECKING:
    from paperless_pilot.api.container import Adapters, Container
    from paperless_pilot.config import Settings

DEMO_MODEL = "demo-modell"
INBOX = 1

_DOCUMENTS: list[tuple[str, str]] = [
    (
        "Scan 2026-10-07 14.25.56.pdf",
        "Muster Möbel GmbH · Hauptstraße 1 · 12345 Musterstadt\nFrau Alex Beispiel\n"
        "Rechnung Nr. 4711\nMusterstadt, den 12.09.2026\nBürostuhl Ergo 249,00 EUR\n"
        "Gesamtbetrag: 249,00 EUR",
    ),
    (
        "Scan 2026-10-07 14.27.25.pdf",
        "Finanzamt Musterstadt\nHerrn Kim Beispiel\nBescheid für 2025 über Einkommensteuer\n"
        "Musterstadt, 03.07.2026\nFestgesetzt werden: 1.234,00 EUR Erstattung",
    ),
    (
        "IMG_0042.pdf",
        "Praxis Dr. Sonne · Allgemeinmedizin\nPatient: Kim Beispiel\n"
        "Arbeitsunfähigkeitsbescheinigung\nAusgestellt am 21.05.2026\n"
        "Voraussichtlich arbeitsunfähig bis 28.05.2026",
    ),
    (
        "Scan 2026-09-01.pdf",
        "Stadtwerke Musterstadt\nFamilie Beispiel\nAbschlagsrechnung Strom\n"
        "Musterstadt, 01.09.2026\nMonatlicher Abschlag: 85,00 EUR",
    ),
    (
        "Brief.pdf",
        "Turnverein Musterstadt 1900 e.V.\nAlex Beispiel\n"
        "Kündigungsbestätigung der Mitgliedschaft\nMusterstadt, den 14.04.2026\n"
        "Wir bestätigen die Kündigung zum 30.06.2026.",
    ),
    (
        "Scan 2026-08-20.pdf",
        "Baumarkt Nord GmbH & Co. KG\nKassenbon\nVerkaufsdatum: 20.08.2026\n"
        "Schrauben, Dübel 12,40 EUR\nSumme 12,40 EUR",
    ),
]

_TYPE_KEYWORDS = [
    ("Bescheid", ("bescheid",)),
    ("Bescheinigung", ("bescheinigung", "bestätigung")),
    ("Kündigung", ("kündigung",)),
    ("Rechnung", ("rechnung", "kassenbon", "summe")),
]
_AREA_KEYWORDS = [
    ("Gesundheit", ("praxis", "patient", "arbeitsunfähig")),
    ("Steuer", ("finanzamt", "einkommensteuer")),
    ("Wohnen", ("strom", "stadtwerke", "baumarkt")),
    ("Freizeit", ("verein",)),
    ("Einkauf", ("rechnung", "kassenbon")),
]
_DATE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{4}")


class DemoPaperless:
    """In-Memory-Paperless mit erfundenen Dokumenten."""

    def __init__(self) -> None:
        now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        self.tags = {INBOX: Tag(id=INBOX, name="Posteingang", document_count=0, is_inbox_tag=True)}
        self.document_types = {50: DocumentType(id=50, name="Sonstiges", document_count=0)}
        self.correspondents = {
            90: Correspondent(id=90, name="o_Sammelordner", document_count=0),
            91: Correspondent(id=91, name="Finanzamt Musterstadt", document_count=0),
            92: Correspondent(id=92, name="Stadtwerke Musterstadt", document_count=0),
        }
        self.documents = {
            i: Document(
                id=i,
                title=name.removesuffix(".pdf"),
                content=content,
                correspondent_id=90,
                document_type_id=50,
                storage_path_id=None,
                tag_ids=(INBOX,),
                created=date(2026, 10, 7),
                page_count=1,
                mime_type="application/pdf",
                original_file_name=name,
                modified=now,
            )
            for i, (name, content) in enumerate(_DOCUMENTS, start=1)
        }
        self._next_id = 1000
        self._modified = now

    async def server_info(self) -> PaperlessInfo:
        inbox = sum(INBOX in d.tag_ids for d in self.documents.values())
        return PaperlessInfo(
            version="Demo",
            api_version=10,
            documents_total=len(self.documents),
            documents_inbox=inbox,
        )

    async def get_document(self, document_id: int) -> Document:
        try:
            return self.documents[document_id]
        except KeyError:
            msg = f"Demo: Dokument {document_id} nicht gefunden"
            raise NotFoundError(msg) from None

    async def iter_documents(self, *, with_all_tags: Sequence[int] = ()) -> AsyncIterator[Document]:
        for document in list(self.documents.values()):
            if set(with_all_tags) <= set(document.tag_ids):
                yield document

    async def list_correspondents(self) -> list[Correspondent]:
        return list(self.correspondents.values())

    async def list_document_types(self) -> list[DocumentType]:
        return list(self.document_types.values())

    async def list_tags(self) -> list[Tag]:
        return list(self.tags.values())

    async def update_document(self, document_id: int, patch: DocumentPatch) -> Document:
        document = await self.get_document(document_id)
        changes = patch.model_dump(exclude_unset=True)
        if "tag_ids" in changes:
            changes["tag_ids"] = tuple(changes["tag_ids"] or ())
        self._modified = max(self._modified, datetime.now(UTC))
        changes["modified"] = self._modified
        updated = document.model_copy(update=changes)
        self.documents[document_id] = updated
        return updated

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def create_tag(self, name: str) -> Tag:
        tag = Tag(id=self._id(), name=name, document_count=0, is_inbox_tag=False)
        self.tags[tag.id] = tag
        return tag

    async def create_document_type(self, name: str) -> DocumentType:
        doc_type = DocumentType(id=self._id(), name=name, document_count=0)
        self.document_types[doc_type.id] = doc_type
        return doc_type

    async def create_correspondent(self, name: str) -> Correspondent:
        correspondent = Correspondent(id=self._id(), name=name, document_count=0)
        self.correspondents[correspondent.id] = correspondent
        return correspondent

    async def get_file(self, document_id: int, kind: FileKind) -> DocumentFile:
        document = await self.get_document(document_id)
        if kind == FileKind.THUMB:
            return DocumentFile(content=_THUMB_SVG, media_type="image/svg+xml")
        return DocumentFile(content=text_pdf(document.content), media_type="application/pdf")


class DemoLlmHost:
    """Regelbasiertes „Modell“: liest Text und erlaubte Werte aus Prompt und Schema."""

    name = "Demo-Rechner"
    base_url = "http://demo.invalid:11434"

    def __init__(self, delay_seconds: float = 0.8) -> None:
        self._delay = delay_seconds

    async def probe(self) -> HostProbe:
        return HostProbe(version="demo", models=(LlmModel(name=DEMO_MODEL, size_bytes=0),))

    async def generate_structured[T: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        output_type: type[T],
        system: str | None = None,
        images: Sequence[bytes] = (),
    ) -> T:
        await asyncio.sleep(self._delay)
        text = prompt.split("<<<", 1)[-1].split(">>>", 1)[0].strip()
        return output_type.model_validate(_answer(text, output_type.model_json_schema()))


def _answer(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    props = schema["properties"]
    lower = text.casefold()
    first_line = text.splitlines()[0].split("·")[0].strip()
    date_match = _DATE.search(text)

    def pick(field: str, rules: list[tuple[str, tuple[str, ...]]], default: str) -> str:
        allowed = _enum(props.get(field, {}), schema)
        for value, words in rules:
            if value in allowed and any(w in lower for w in words):
                return value
        return default if default in allowed else (allowed[0] if allowed else default)

    answer: dict[str, Any] = {
        "document_type": pick("document_type", _TYPE_KEYWORDS, "Sonstiges"),
        "correspondent": first_line,
        "correspondent_evidence": first_line,
        "document_date": date_match.group(0) if date_match else None,
        "date_evidence": _line_with(text, date_match.group(0)) if date_match else None,
        "title": _title(text),
    }
    if "persons" in props:
        allowed = _enum(props["persons"].get("items", {}), schema)
        answer["persons"] = [p for p in allowed if p.casefold() in lower]
    if "area" in props:
        answer["area"] = pick("area", _AREA_KEYWORDS, "Sonstiges")
    return answer


def _line_with(text: str, needle: str) -> str:
    return next(line.strip() for line in text.splitlines() if needle in line)


def _enum(prop: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if "$ref" in prop:
        prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[-1]]
    return list(prop.get("enum", []))


def _title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()[1:] if line.strip()]
    for line in lines:
        if not _DATE.search(line) and "Beispiel" not in line:  # erfundene Namen überspringen
            return " ".join(line.split()[:6])
    return "Dokument"


def text_pdf(text: str) -> bytes:
    """Minimales einseitiges PDF mit dem Text (Helvetica, WinAnsi)."""

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lines = [escape(line) for line in text.splitlines()]
    stream = "BT /F1 13 Tf 60 780 Td 18 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    content = stream.encode("cp1252", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


_THUMB_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 80">'
    b'<rect width="60" height="80" fill="#f4f4f5"/><path d="M10 15h40M10 25h30M10 35h35" '
    b'stroke="#a1a1aa" stroke-width="3"/></svg>'
)


@asynccontextmanager
async def demo_adapters(_settings: "Settings") -> AsyncIterator["Adapters"]:
    from paperless_pilot.api.container import Adapters  # noqa: PLC0415 - vermeidet Zyklus

    yield Adapters(paperless=DemoPaperless(), hosts=[DemoLlmHost()])


async def seed_demo(container: "Container") -> None:
    """Beispiel-Taxonomie einspielen, in „Paperless“ anlegen und den Posteingang einreihen."""
    _, configured = await container.taxonomy_repository.get()
    if not configured:
        data = json.loads(
            resources.files("paperless_pilot").joinpath("taxonomy.example.json").read_text("utf-8")
        )
        await container.taxonomy.save(Taxonomy.model_validate(data))
    await container.taxonomy.apply_sync()
    await container.intake.enqueue_inbox()
