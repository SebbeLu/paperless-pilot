# paperless-pilot – Konzept

Stand: 2026-10-30 · Status: Entwurf

## 1. Ziel

Ein Dienst als Docker-Container auf dem Unraid, der Dokumente in Paperless-ngx mit lokalen LLMs (Ollama) automatisch bearbeitet: Er verbessert die OCR, vergibt Titel, Korrespondent, Dokumenttyp, Tags und benutzerdefinierte Felder und sorgt für saubere Dateinamen. Er arbeitet immer dann, wenn ein Ollama-Rechner im Netz verfügbar ist. Dazu kommt eine moderne, selbsterklärende Web-Oberfläche zum Prüfen, Aufräumen und Steuern.

Qualitätsanspruch: Alles ist durch Tests abgesichert, sauber programmiert und architektonisch auf aktuellem Stand.

## 2. Ausgangslage (Analyse vom 2026-10-30)

| | |
|---|---|
| Paperless-ngx | 3.2.1 im Heimnetz |
| Dokumente | 709 (≈ 2.000 Seiten), 95 im Tag `INBOX`, 55 mit `INBOX(Mail)` |
| Titel wie Dateinamen | 138 (z. B. „SwiftScan 2026-10-07 14.25.56“) |
| Schwacher OCR-Text | 79 Dokumente |
| Korrespondenten | 44, davon 21 ungenutzt; Sammel-Korrespondenten `o_Ärzte`, `o_Behörden`, `o_Online-Shops` usw. für > 60 % des Bestands |
| Dokumenttypen | 30, davon 15 nur einmal benutzt; deutsch und englisch doppelt (Rechnung/Invoice, Vertrag/Contract) |
| Tags | 106, davon 74 nur einmal benutzt; Müll-Tags aus einem früheren KI-Tool (`{}`, `,`, `custom_fields`, …) |
| Benutzerdefinierte Felder, Speicherpfade, Workflows | keine |
| Eingebaute KI (Paperless 3.2) | vorhanden, aber nicht aktiviert |

**Lehre aus dem früheren KI-Versuch:** Ungeprüfte Modellausgaben wurden direkt in Paperless geschrieben. Für paperless-pilot gilt deshalb:
- Jede Modellantwort wird gegen ein Schema geprüft.
- Neue Stammdaten (Tags, Typen, Korrespondenten) entstehen nur nach Freigabe.
- Die Ausgabesprache ist Deutsch.

## 3. Entscheidungen

| # | Entscheidung | Datum |
|---|---|---|
| E1 | Eigenentwicklung statt paperless-gpt, paperless-ai oder der Paperless-KI | 2026-10-30 |
| E2 | Korrespondent = **echter Absender**; die `o_…`-Sammel-Korrespondenten werden aufgelöst | 2026-10-30 |
| E3 | Mac (M4 Pro, 48 GB) ist Hauptarbeiter, aber nur **bei Leerlauf und abends**, mit Pause-Schalter | 2026-10-30 |
| E4 | Gaming-PC (GTX 1070, 8 GB) wird bei Rückstand **per Wake-on-LAN geweckt** und danach wieder schlafen gelegt | 2026-10-30 |
| E5 | Repository privat auf **GitHub**, CI mit GitHub Actions, Image in der GitHub Container Registry (GHCR) | 2026-10-30 |
| E6 | Name: **paperless-pilot** | 2026-10-30 |
| E7 | Möglichst viel Automatik; Vertrauen wird je Feld aus deinen Übernahmen gelernt (siehe Abschnitt 7) | 2026-10-30 |
| A1 | Personen bleiben Tags, kein eigenes Feld | 2026-10-30 |
| E8 | Ziel-Taxonomie abgestimmt (enthält persönliche Daten und liegt deshalb nicht im Repo) | 2026-10-30 |

## 4. Zielbild der Ordnung in Paperless

- **Korrespondent:** der echte Absender („Praxis Dr. Muster“, „Finanzamt Musterstadt“). Er wird gegen die vorhandene Liste abgeglichen; neue Korrespondenten kommen nur als Vorschlag.
- **Dokumenttyp:** eine feste deutsche Liste mit etwa 12–15 Einträgen (Rechnung, Vertrag, Bescheid, Bescheinigung, Gehaltsabrechnung, Arztbrief, Rezept, Kontoauszug, Versicherungsschein, Kündigung, Brief, Sonstiges …). Die genaue Liste wird in Phase 1 festgelegt.
- **Tags:**
  - Personen: ein Tag je Haushaltsmitglied
  - Lebensbereiche: Gesundheit, Steuer, Auto, Wohnung, Arbeit, Finanzen, Versicherung, Kinder
  - Status: `ai:todo`, `ai:prüfen`, `ai:fertig`, `ai:fehler`
- **Benutzerdefinierte Felder (je Dokumenttyp):** Betrag, Rechnungsnummer, Fälligkeit, Kunden-/Vertragsnummer, Laufzeit bis, Kündigungsfrist.
- **Speicherpfad:** `{Person}/{Jahr}/{Korrespondent}/{Datum} {Titel}`. Die Dateien benennt Paperless um, das Tool setzt nur die Felder.
- **Titel:** Vorlage je Dokumenttyp, z. B. `Rechnung {Rechnungsnummer} – {Monat Jahr}`. Das Modell schlägt nur den freien Teil vor.
- Die automatische Zuordnung von Paperless („Auto“) wird für Objekte abgeschaltet, die das Tool verwaltet.

## 5. Architektur

```
┌──────────────── Unraid ────────────────┐
│ Paperless-ngx  ◀──REST──▶  paperless-pilot (1 Container)
│   Workflow: neu → ai:todo    ├─ API (FastAPI) + Web-UI (SPA)
│                              ├─ Scheduler / Worker-Pool
│                              ├─ Job-Queue (SQLite, WAL)
│                              └─ Änderungsprotokoll (Undo)
│ Home Assistant  ◀────────────┘  Verfügbarkeit, WoL, Fristen
└────────────────────────────────────────┘
          │ Ollama-API
   ┌──────┴───────┐
   Mac (Hauptarbeiter)     Gaming-PC (Nebenarbeiter)
```

**Ports & Adapters (hexagonale Architektur):** Der Domänenkern enthält Pipeline, Regeln, Konfidenz und Vertrauensmodell. Er kennt weder Paperless noch Ollama noch Home Assistant, sondern nur Schnittstellen (Ports):
- `DocumentRepository`: Lesen und Schreiben von Dokumenten (Adapter: Paperless-REST)
- `LlmProvider`: Text, Vision und strukturierte Ausgabe (Adapter: Ollama, später optional andere)
- `AvailabilitySource`: Ist ein Rechner nutzbar? (Adapter: Zeitfenster, Home Assistant, manuell)
- `HostPower`: Rechner wecken bzw. schlafen legen (Adapter: Home Assistant)
- `Notifier`: Meldungen (Adapter: Home Assistant, ntfy)

So lässt sich der Kern vollständig mit Attrappen testen; die Adapter bekommen eigene Vertrags- und Integrationstests.

**Durable Queue:** Jeder Job steht für ein Dokument und einen Schritt. Jobs sind idempotent, haben Leases, werden bei Fehlern wiederholt (mit wachsendem Abstand) und landen bei Dauerfehlern in einer Fehlerliste. Fällt ein Rechner mitten im Job aus, übernimmt ein anderer.

## 6. Verarbeitungs-Pipeline

1. **Aufnehmen:** Ein Paperless-Workflow setzt bei neuen Dokumenten `ai:todo`; der Dienst holt sie per Polling ab. Der Bestand wird einmalig per Rückstand-Import eingereiht.
2. **OCR-Qualität bewerten:** Zeichen pro Seite, Anteil von Buchstaben und Wörtern und Wörterbuchtreffer. Nur schlechte Seiten gehen zum Vision-Modell. Das Original-OCR bleibt erhalten, kritische Werte (IBAN-Prüfziffer, Beträge, Daten) werden gegengeprüft.
3. **Klassifizieren:** Dokumenttyp, Person(en) und Lebensbereich.
4. **Extrahieren:** Korrespondent, Datum und die Felder des jeweiligen Dokumenttyps. Die Ausgabe wird gegen ein Schema geprüft (Ollama `format` mit JSON-Schema aus Pydantic).
5. **Abgleichen:** Der Korrespondent wird per unscharfem Abgleich mit Alias-Liste zugeordnet; unbekannte Werte werden zu Vorschlägen.
6. **Titel bilden:** aus der Vorlage des Dokumenttyps.
7. **Entscheiden:** Liegt die Konfidenz eines Feldes über seiner gelernten Schwelle, wird es automatisch übernommen, sonst kommt das Dokument in die Prüfliste.
8. **Zurückschreiben:** Die alten Werte werden protokolliert, sodass sich jede Änderung rückgängig machen lässt.

## 7. Automatik und Vertrauen

- **Einschwingphase:** Alle Vorschläge gehen zunächst in die Prüfliste.
- Für jede Kombination aus Feld und Dokumenttyp misst das Tool die **Übernahmequote** (unverändert übernommen ÷ geprüft).
- Ab einer Mindestzahl an Prüfungen und einer Quote ≥ Ziel (Standard 95 %) wird diese Kombination **automatisch** übernommen. Steigt die Korrekturrate wieder, fällt sie zurück in die Prüfung.
- **Korrekturen werden zu Beispielen** im Prompt, je Korrespondent bzw. Dokumenttyp. Das Tool wird so ohne Nachtraining des Modells besser.
- Stichproben: Auch automatisch übernommene Felder landen gelegentlich in der Prüfliste, damit die Quote ehrlich bleibt.

## 8. Rechner und Verfügbarkeit

| Rechner | Fähigkeiten | Verfügbar, wenn | Energie |
|---|---|---|---|
| Mac M4 Pro 48 GB | Text + Vision, große Modelle (z. B. `gemma4:26b`) | Leerlauf ≥ X min (HA-Companion-App, Sensor „Active“) **oder** im Zeitfenster abends/nachts; nicht pausiert | – |
| Gaming-PC GTX 1070 | nur Text, kleine Modelle (≤ 8 GB VRAM) | online und es wird nicht gespielt (HASS.Agent-Sensor) | WoL über HA bei Rückstand in der Nacht; Schlafen über HASS.Agent, wenn die Warteschlange leer ist |

- Für jeden Rechner werden Fähigkeiten, Modelle und Durchsatz gemessen. Der Scheduler verteilt Jobs nach den benötigten Fähigkeiten (Vision-Jobs nur an den Mac).
- Fehlende Modelle werden automatisch nachgeladen (`ollama pull`).
- Ein Ollama-Rechner muss im Netz lauschen: `OLLAMA_HOST=0.0.0.0` plus Firewall-Freigabe für Port 11434. Beim Gaming-PC ist das noch offen.

## 9. Modellwahl

Es werden keine Modelle fest verdrahtet. Rollen werden per Konfiguration auf Modelle abgebildet:

| Rolle | Startkandidat | Vergleich |
|---|---|---|
| Vision-OCR | `gemma4:26b` (Mac) | Qwen-VL-Familie |
| Extraktion | `gemma4:26b` (Mac) | Qwen3, Mistral Small |
| leichte Klassifikation | kleines Modell (Gaming-PC) | – |

Die Entscheidung trifft der **Benchmark**: 30–50 Dokumente aus deinem Bestand, einmal korrekt erfasst, dienen als Goldstandard. Jedes Modell wird dagegen Feld für Feld gemessen (Genauigkeit und Sekunden pro Dokument).

## 10. Oberfläche (UX)

Leitlinien: selbsterklärend, mit der Tastatur bedienbar, sofortige Rückmeldung, jede Aktion lässt sich rückgängig machen, keine Einstellungsseiten ohne Vorschau.

1. **Übersicht:** Rückstand, Fortschritt, Rechner-Status („Mac 🟢 arbeitet · Gaming-PC 💤 schläft“), Fehler, nächste Fristen.
2. **Prüfen:** funktioniert wie ein Posteingang. Links das PDF, rechts die Änderungen als Vorher/Nachher mit Konfidenz je Feld. `Enter` übernimmt, `E` bearbeitet, `J`/`K` blättert. Gleichartige Vorschläge lassen sich gesammelt übernehmen.
3. **Aufräumen:** Zusammenführungs-Vorschläge für Korrespondenten, Tags und Typen, Auflösung der `o_…`-Sammel-Korrespondenten, Löschen der Müll-Tags und Hinweise auf Dubletten.
4. **Regeln:** Dokumenttypen mit ihren Feldern und Titel-Vorlagen, mit Live-Vorschau an echten Dokumenten.
5. **Rechner & Modelle:** Verfügbarkeitsregeln, Pause, Benchmark.
6. **Verlauf:** jede Änderung mit Rückgängig.

## 11. Technik und Qualität

- **Backend:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, SQLite (WAL), httpx; Abhängigkeiten mit `uv`, Linting mit `ruff`, strikte Typprüfung mit `mypy` bzw. `pyright`.
- **Frontend:** React + TypeScript (strict), Vite, TanStack Query/Router, shadcn/ui + Tailwind, PDF.js. Der API-Client wird aus der OpenAPI-Beschreibung erzeugt; Live-Updates laufen über SSE.
- **Tests:**
  - Unit-Tests für den Kern (pytest, Hypothesis für Parser und Validierung)
  - Vertragstests gegen die Paperless-API mit aufgezeichneten Antworten (respx)
  - Integrationstests mit einem echten Paperless-ngx 3.2 über testcontainers
  - Frontend mit Vitest + Testing Library, E2E mit Playwright
  - LLM-Bewertung gegen den Goldstandard, getrennt von der CI
- **CI (GitHub Actions):** Lint, Typprüfung, Tests und Coverage-Grenze; danach Multi-Arch-Image nach GHCR.
- **Betrieb:** ein Container mit Healthcheck und Unraid-Template; Konfiguration per Umgebungsvariablen plus UI; Secrets nur als Variablen bzw. Dateien.
- **Sicherheit:** Login für die UI (lokaler Benutzer oder Weiterleitung an einen Auth-Proxy), Paperless-Token mit minimal nötigen Rechten.

## 12. Bestandsmigration

1. **Sicherung:** Paperless-Export (`document_exporter`) vor der ersten Schreibaktion.
2. **Aufräumen der Stammdaten:** Müll-Tags löschen, Dubletten zusammenführen, Ziel-Dokumenttypen anlegen und alte darauf abbilden. Das geschieht halbautomatisch in der Oberfläche „Aufräumen“, mit deiner Freigabe.
3. **Neubewertung des Bestands** über die Pipeline: zuerst eine Stichprobe von 50 Dokumenten (Einschwingphase), danach der Rest nachts.
4. **Auflösen der `o_…`-Korrespondenten:** über die echten Absender aus Schritt 3; danach werden sie gelöscht.

## 13. Fahrplan

| Phase | Inhalt |
|---|---|
| 0 – Fundament | Repository, CI, Grundgerüst (Backend, Frontend, Container), Paperless- und Ollama-Adapter mit Tests |
| 1 – Kernnutzen | Worker-Pool und Verfügbarkeit, Queue, Klassifikation und Extraktion, Titel, Prüfliste, Änderungsprotokoll mit Undo, Übersicht |
| 2 – Ordnung | Aufräumen, Felder je Dokumenttyp, Speicherpfade, Vision-OCR, gelerntes Vertrauen, Benchmark |
| 3 – Mehrwert | Fristen an HA, Dubletten, Steuer-Export, semantische Suche bzw. Chat, Trennung mehrerer Dokumente in einem Scan |

## 14. Offene Punkte

- ~~Personen als Tags oder als eigenes Feld~~ → entschieden: Tags (A1)
- ~~Endgültige Liste der Dokumenttypen und Lebensbereiche~~ → abgestimmt (privat, nicht im Repo)
- Gaming-PC: Ollama im Netz freigeben, WoL im BIOS aktivieren, HASS.Agent installieren
- Mac: HA-Companion-App mit Sensor „Active“ vorhanden?
- Zeitfenster „abends“ konkret festlegen
- ~~Wie werden die Mail-Dokumente (`INBOX(Mail)`) behandelt?~~ → Tag entfällt
