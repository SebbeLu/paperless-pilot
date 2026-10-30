# paperless-pilot

Bearbeitet Dokumente in [Paperless-ngx](https://docs.paperless-ngx.com/) automatisch mit lokalen Sprachmodellen über [Ollama](https://ollama.com/): bessere OCR, Titel, Korrespondent, Dokumenttyp, Tags und Felder. Gearbeitet wird, sobald ein Ollama-Rechner im Netz verfügbar ist. Eine Web-Oberfläche dient zum Prüfen, Aufräumen und Steuern.

- Konzept: [docs/konzept.md](docs/konzept.md)
- Plan Phase 1: [docs/phase-1.md](docs/phase-1.md)

**Stand:** Phase 0 (Fundament): Grundgerüst, Anbindung an Paperless und Ollama, Übersichtsseite mit Systemstatus.

## Aufbau

```
backend/    Python 3.13 · FastAPI · Pydantic · httpx       (uv)
  src/paperless_pilot/
    domain/        Modell, Ports (Schnittstellen), Fehler – kennt keine Technik
    application/   Anwendungsfälle (z. B. Systemstatus)
    adapters/      Paperless-REST, Ollama
    api/           FastAPI-App, Routen, Auslieferung des Frontends
  tests/
    unit/          Kern und API mit Attrappen
    contract/      Adapter gegen nachgebildete API-Antworten (respx)
    integration/   Adapter gegen echtes Paperless im Container (Docker, läuft in der CI)
frontend/   React · TypeScript · Vite · TanStack Router/Query · Tailwind (npm)
  openapi.json     vom Backend erzeugt → src/api/schema.d.ts (typisierter Client)
Dockerfile  Ein Container: gebautes Frontend + Backend
```

## Entwicklung

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Node 24.

```bash
cd backend && uv sync
```

```bash
cd frontend && npm ci
```

Lokale Konfiguration in `backend/.env` (wird nicht eingecheckt):

```dotenv
PILOT_PAPERLESS_URL=http://paperless.local:8000
PILOT_PAPERLESS_TOKEN_FILE=/Users/<du>/.config/paperless-pilot/token
PILOT_OLLAMA_HOSTS=[{"name": "Mac", "url": "http://mac.local:11434"}]
```

Starten (zwei Terminals); das Frontend leitet `/api` an Port 8080 weiter:

```bash
cd backend && uv run paperless-pilot
```

```bash
cd frontend && npm run dev
```

### Prüfen

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run pytest --cov
```

```bash
cd frontend && npm run lint && npm run typecheck && npx vitest run --coverage && npm run build
```

Ändert sich die API, Beschreibung und Typen neu erzeugen (die CI prüft, dass beide aktuell sind):

```bash
cd backend && uv run python -m paperless_pilot.api.openapi_export ../frontend/openapi.json && cd ../frontend && npm run gen:api
```

## Konfiguration

| Variable | Pflicht | Bedeutung |
|---|---|---|
| `PILOT_PAPERLESS_URL` | ja | Adresse von Paperless-ngx |
| `PILOT_PAPERLESS_TOKEN` oder `PILOT_PAPERLESS_TOKEN_FILE` | ja | API-Token (Datei bevorzugt, z. B. als Docker-Secret) |
| `PILOT_OLLAMA_HOSTS` | nein | JSON-Liste `[{"name": …, "url": …}]` |
| `PILOT_HTTP_TIMEOUT_SECONDS` | nein | Zeitlimit für Paperless-Anfragen (Standard 10) |
| `PILOT_LLM_TIMEOUT_SECONDS` | nein | Zeitlimit für Modellanfragen (Standard 600) |
| `PILOT_PORT` | nein | Port der Web-Oberfläche (Standard 8080) |

## Betrieb auf Unraid

Die CI baut bei jedem Push auf `main` das Image `ghcr.io/sebbelu/paperless-pilot:latest` (amd64 und arm64).

```bash
docker run -d --name paperless-pilot -p 8080:8080 -e PILOT_PAPERLESS_URL=http://paperless.local:8000 -e PILOT_PAPERLESS_TOKEN_FILE=/run/secrets/paperless_token -e 'PILOT_OLLAMA_HOSTS=[{"name":"Mac","url":"http://mac.local:11434"}]' -v /mnt/user/appdata/paperless-pilot/token:/run/secrets/paperless_token:ro ghcr.io/sebbelu/paperless-pilot:latest
```

Damit ein Ollama-Rechner erreichbar ist, muss Ollama im Netz lauschen (`OLLAMA_HOST=0.0.0.0`, Port 11434 freigeben).

## Technische Entscheidungen

- **TypeScript 5.9 statt 7:** `openapi-typescript` braucht die JavaScript-API von TypeScript, die es ab Version 7 nicht mehr gibt, und verlangt per Peer-Dependency TypeScript 5. Umstieg, sobald der Generator neuere Versionen unterstützt.
- **Paperless-API-Version 10 fest eingestellt:** passt zu Paperless-ngx 3.2. Ein Wechsel wird bewusst über den Integrationstest abgesichert.
