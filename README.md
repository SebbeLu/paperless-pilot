# paperless-pilot

Bearbeitet Dokumente in [Paperless-ngx](https://docs.paperless-ngx.com/) automatisch mit lokalen Sprachmodellen über [Ollama](https://ollama.com/). Für jedes Dokument schlägt es Dokumenttyp, Absender, Datum, Personen, Lebensbereich und Titel vor, und zwar dann, wenn ein Ollama-Rechner im Netz verfügbar ist und arbeiten darf. Jeder Vorschlag wird nachgeprüft (Belegzitat im Text, plausibles Datum, bekannter Absender), landet in einer Prüfliste und wird erst nach deiner Freigabe in Paperless geschrieben. Jede Änderung lässt sich rückgängig machen.

- Konzept: [docs/konzept.md](docs/konzept.md)
- Plan und Umsetzung Phase 1: [docs/phase-1.md](docs/phase-1.md)

**Stand:** Phase 1 (Kernnutzen) ist umgesetzt.

## Funktionen

| Bereich | Was er tut |
|---|---|
| **Übersicht** | Kennzahlen (Dokumente, Posteingang, zu prüfen, wartend, Fehler), „Posteingang einreihen“, Verbindungsstatus |
| **Prüfen** | Liste mit unsicheren Vorschlägen zuerst, PDF-Vorschau, Formular mit bisherigem Wert, Vorschlag, Prüfergebnis und Belegzitat; mehrere oder alle Vorschläge markieren und gemeinsam unverändert übernehmen (Konflikte bleiben offen); Bedienung per Tastatur |
| **Verlauf** | Jede Schreibaktion mit Vorher→Nachher und Rückgängig (mit Konfliktprüfung) |
| **Regeln** | Taxonomie: Dokumenttypen, Personen (mit Aliasen), Lebensbereiche, Status-Tags; Abgleich mit Paperless, Import/Export; gelernte Korrekturen ansehen und vergessen |
| **Rechner & Modelle** | Status je Ollama-Rechner mit Begründung („Wartet: Rechner wird benutzt, Zeitfenster ab 20:00“), Pause, Zeitfenster, Leerlauf und Sperre über Home Assistant |

**Tastatur in „Prüfen“:** `Enter` übernehmen · `J`/`K` nächster/voriger · `R` verwerfen · `E` ins erste unsichere Feld · `X` markieren · `Z` letzte Übernahme rückgängig (bei gemeinsamer Übernahme alle) · `Esc` Feld verlassen · `?` Hilfe

### So läuft ein Dokument durch

1. Ein Paperless-Workflow setzt bei neuen Dokumenten den Tag `ai:todo`. Den bestehenden Rückstand reihst du mit „Posteingang einreihen“ ein.
2. paperless-pilot holt die Dokumente minütlich ab. Darf ein Rechner arbeiten, liest das Modell das Dokument aus. Das Antwortschema wird aus deiner Taxonomie erzeugt, deshalb sind nur erlaubte Werte möglich.
3. Der Vorschlag wird geprüft und landet in der Prüfliste. In Paperless wechselt der Tag zu `ai:prüfen`.
4. Beim Übernehmen werden Typ, Absender, Datum, Titel sowie die Personen- und Lebensbereich-Tags gesetzt, andere Tags bleiben erhalten. Danach trägt das Dokument `ai:fertig`, und der Posteingangs-Tag wird entfernt (abschaltbar).

### Lernen aus Korrekturen

Änderst du beim Übernehmen einen Vorschlag, merkt sich paperless-pilot die Korrektur: was das Modell vorgeschlagen hat, was richtig war, den Textanfang und den Dateinamen. Bei ähnlichen Dokumenten bekommt das Modell bis zu drei solcher Korrekturen als Beispiel im Prompt. Das Modell selbst wird nicht nachtrainiert.

- **Ähnlich** heißt: ähnlicher Textanfang, verstärkt durch den Absender des Beispiels im Text. Bei Dokumenten fast ohne Text (z. B. Fotos, deren OCR nur Zeichensalat liefert) zählt stattdessen ein ähnlicher Dateiname.
- **Keine Korrektur** ist es, wenn ein leerer Vorschlag einfach den bisherigen Wert behält oder ein neuer Absender wie vorgeschlagen angelegt wird.
- Ein Dokument lernt nie von sich selbst. Machst du eine Übernahme rückgängig, gilt auch ihre Korrektur nicht mehr.
- Unter *Regeln → Gelernte Korrekturen* lässt sich eine falsche Korrektur vergessen. In *Prüfen* steht, wie viele Korrekturen ein Vorschlag berücksichtigt hat.
- Übernahmen von vor dieser Funktion werden beim Start einmalig nachgelernt.

## Ausprobieren ohne eigene Infrastruktur

Der Demo-Modus nutzt erfundene Dokumente und ein regelbasiertes „Modell“ statt Paperless und Ollama:

```bash
docker run --rm -p 8080:8080 -e PILOT_DEMO=true ghcr.io/sebbelu/paperless-pilot:latest
```

Danach `http://localhost:8080` öffnen.

## Betrieb auf Unraid

Die CI baut bei jedem Push auf `main` das Image `ghcr.io/sebbelu/paperless-pilot:latest` (amd64 und arm64). Für Unraid liegt eine Vorlage in [unraid/paperless-pilot.xml](unraid/paperless-pilot.xml). Im Unraid-Terminal laden:

```bash
curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-paperless-pilot.xml https://raw.githubusercontent.com/SebbeLu/paperless-pilot/main/unraid/paperless-pilot.xml
```

Danach unter *Docker → Add Container* die Vorlage „paperless-pilot“ wählen. Der Container läuft als `99:100` (nobody:users), damit er in `appdata` schreiben darf. Ohne Unraid geht es auch mit `docker run`:

```bash
docker run -d --name paperless-pilot -p 8080:8080 -v /mnt/user/appdata/paperless-pilot:/data -e PILOT_PAPERLESS_URL=http://paperless.local:8000 -e PILOT_PAPERLESS_TOKEN_FILE=/data/paperless_token -e 'PILOT_OLLAMA_HOSTS=[{"name":"Mac","url":"http://mac.local:11434"}]' ghcr.io/sebbelu/paperless-pilot:latest
```

**Einrichtung:**
1. **Paperless-Token:** In Paperless unter *Mein Profil* einen API-Token erzeugen und in `/mnt/user/appdata/paperless-pilot/paperless_token` ablegen (lesbar für den Container-Benutzer).
2. **Ollama-Rechner:** Ollama muss im Netz lauschen (`OLLAMA_HOST=0.0.0.0`, Port 11434 freigeben). Das Modell holst du mit `ollama pull gemma4:26b`.
3. **Taxonomie:** In der Oberfläche unter *Regeln* anlegen oder eine Sicherung importieren, danach *In Paperless anlegen*.
4. **Workflow in Paperless:** Auslöser „Dokument hinzugefügt“, Aktion „Tag `ai:todo` zuweisen“.
5. **Optional Home Assistant:** `PILOT_HA_URL` und einen Long-Lived Access Token (`PILOT_HA_TOKEN_FILE`) setzen. Unter *Rechner & Modelle* trägst du dann z. B. `binary_sensor.<mac>_active` als Leerlauf-Entität ein.

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `PILOT_PAPERLESS_URL` | – | Adresse von Paperless-ngx (Pflicht außer im Demo-Modus) |
| `PILOT_PAPERLESS_TOKEN` / `PILOT_PAPERLESS_TOKEN_FILE` | – | API-Token (Datei bevorzugt) |
| `PILOT_OLLAMA_HOSTS` | `[]` | JSON-Liste `[{"name": …, "url": …, "model": …}]`; `model` optional je Rechner |
| `PILOT_EXTRACTION_MODEL` | `gemma4:26b` | Standardmodell fürs Auslesen |
| `PILOT_HA_URL` | – | Home Assistant (optional) |
| `PILOT_HA_TOKEN` / `PILOT_HA_TOKEN_FILE` | – | Long-Lived Access Token für Home Assistant |
| `PILOT_DATA_DIR` | `/data` | SQLite-Datenbank (Aufträge, Vorschläge, Verlauf, Taxonomie, Rechner-Regeln, gelernte Korrekturen) |
| `PILOT_TIMEZONE` | `Europe/Berlin` | Für Zeitfenster und Datumsprüfungen |
| `PILOT_INTAKE_INTERVAL_SECONDS` | `60` | Takt des Eingangs (`ai:todo`) |
| `PILOT_HOST_PROBE_INTERVAL_SECONDS` | `30` | Takt der Rechner-Prüfung |
| `PILOT_LLM_TIMEOUT_SECONDS` | `600` | Zeitlimit je Modellanfrage |
| `PILOT_DEMO` | `false` | Demo-Modus mit erfundenen Daten |
| `PILOT_PORT` | `8080` | Port der Oberfläche |

## Aufbau

```
backend/    Python 3.13 · FastAPI · Pydantic · SQLAlchemy/Alembic (SQLite) · httpx   (uv)
  src/paperless_pilot/
    domain/        Modell, Regeln (Taxonomie, Freigaben, Auslesen, Abgleich, Lernen), Ports – ohne Technik
    application/   Anwendungsfälle: Auslesen, Eingang, Scheduler, Rechner, Prüfen, Verlauf, Taxonomie, Lernen
    adapters/      Paperless-REST, Ollama, Home Assistant, Datenbank, Demo
    api/           FastAPI-Routen, Server-Sent Events, Verdrahtung, Auslieferung des Frontends
  tests/           unit · db · flow (Abläufe mit Attrappen) · contract (respx) · api · integration
frontend/   React · TypeScript · Vite · TanStack Router/Query · Tailwind            (npm)
  e2e/             Playwright gegen das Backend im Demo-Modus
Dockerfile  Ein Container: gebautes Frontend + Backend, Volume /data
```

## Entwicklung

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Node 24.

```bash
cd backend && uv sync
```

```bash
cd frontend && npm ci
```

Lokale Konfiguration in `backend/.env` (wird nicht eingecheckt), z. B. `PILOT_PAPERLESS_URL`, `PILOT_PAPERLESS_TOKEN_FILE`, `PILOT_OLLAMA_HOSTS` und `PILOT_DATA_DIR=./.data`. Starten (zwei Terminals); das Frontend leitet `/api` an Port 8080 weiter:

```bash
cd backend && uv run paperless-pilot
```

```bash
cd frontend && npm run dev
```

Ein Dokument probeweise auslesen, ohne etwas zu schreiben:

```bash
cd backend && uv run paperless-pilot extract 123
```

### Prüfen

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy src tests && uv run pytest --cov
```

```bash
cd frontend && npm run lint && npm run typecheck && npx vitest run --coverage && npm run e2e
```

Ändert sich die API, Beschreibung und Typen neu erzeugen (die CI prüft, dass beide aktuell sind):

```bash
cd backend && uv run python -m paperless_pilot.api.openapi_export ../frontend/openapi.json && cd ../frontend && npm run gen:api
```

## Technische Entscheidungen

- **Erzwingen statt glauben:** Erlaubte Werte stehen als `enum` im JSON-Schema, das Ollama bei der Erzeugung erzwingt. Absender und Datum müssen mit einem wörtlichen Zitat belegt werden, das gegen den OCR-Text geprüft wird.
- **Datum als `TT.MM.JJJJ`:** Im Probelauf haben Modelle ISO-Daten verdreht, deutsche Daten nicht. Das Parsen übernimmt der Code.
- **Denkmodus aus** (`think: false`): Bei strukturierter Ausgabe bringt er keine besseren Ergebnisse, war aber um ein Vielfaches langsamer.
- **SQLite statt Redis/Postgres:** Ein Container ohne weitere Dienste. Leases per `UPDATE … RETURNING` reichen für wenige Arbeiter.
- **TypeScript 5.9 statt 7:** `openapi-typescript` braucht die JavaScript-API von TypeScript, die es ab Version 7 nicht mehr gibt.
- **Paperless-API-Version 10 fest eingestellt:** Das passt zu Paperless-ngx 3.2.
