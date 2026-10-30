# Phase 1 – Kernnutzen: Plan

Stand: 2026-10-30 · Status: abgestimmt · Grundlage: [konzept.md](konzept.md)

## 1. Ziel

Am Ende von Phase 1 kann paperless-pilot den Posteingang abarbeiten:

1. Neue Dokumente landen automatisch in der Warteschlange.
2. Sobald ein Ollama-Rechner verfügbar ist und arbeiten darf, liest ein Modell Dokumenttyp, Korrespondent, Datum, Personen, Lebensbereich und einen Titel aus.
3. Jeder Vorschlag landet in der **Prüfliste**. Dort wird er mit der Tastatur übernommen, korrigiert oder verworfen.
4. Erst nach der Freigabe wird in Paperless geschrieben. Jede Änderung steht im **Verlauf** und lässt sich rückgängig machen.

**Bewusst nicht in Phase 1** (kommt in Phase 2):
- vollautomatische Übernahme und gelerntes Vertrauen,
- Vision-OCR,
- Felder je Dokumenttyp wie Betrag oder Fälligkeit,
- Speicherpfade,
- Aufräumen der alten Taxonomie,
- Titel-Vorlagen und Felder im Regel-Editor (der Taxonomie-Editor kommt schon in Phase 1),
- Wake-on-LAN über Home Assistant.

Phase 1 ist damit die **Einschwingphase**. Deine Prüfungen liefern die Daten, aus denen Phase 2 lernt, wann das Tool selbst übernehmen darf.

## 2. Ablauf eines Dokuments

```
Paperless                 paperless-pilot                                  Ollama-Rechner
─────────                 ───────────────                                  ──────────────
neues Dokument
  └─ Workflow: Tag ai:todo
                          Eingang (alle 60 s): Dokumente mit ai:todo
                            └─ Auftrag „auslesen“ anlegen (idempotent)
                          Scheduler: Rechner online, Zeitfenster offen,
                            nicht pausiert, Modell vorhanden?
                            └─ Auftrag leasen ──────────────────────────▶  strukturierte Ausgabe
                          Prüfen & Abgleichen  ◀──────────────────────────  (JSON-Schema)
                            ├─ Schema/Plausibilität ok → Vorschlag
                            │    └─ Paperless: ai:todo → ai:prüfen
                            └─ Fehler → Wiederholung mit Abstand, zuletzt ai:fehler
Prüfliste (Mensch)
  Übernehmen ─────────────▶ Konflikt-Check → PATCH an Paperless → Verlauf
                            └─ Paperless: ai:prüfen → ai:fertig, INBOX entfernen
  Rückgängig ─────────────▶ alte Werte zurückschreiben (mit Konflikt-Check)
```

**Status in Paperless sichtbar:** Die Tags `ai:todo`, `ai:prüfen`, `ai:fertig` und `ai:fehler` zeigen den Stand auch in Paperless selbst. Den Rückstand stößt du an, indem du `ai:todo` per Massenbearbeitung vergibst oder in der Oberfläche auf „Posteingang einreihen“ klickst.

## 3. Taxonomie: in der Datenbank, gepflegt in der Oberfläche

Die Ziel-Taxonomie ist persönlich und gehört nicht ins öffentliche Repo. Sie liegt in der SQLite-Datenbank im Datenordner des Containers und wird im Bereich **Regeln → Taxonomie** gepflegt (Entscheidung D3).

**Inhalt:**
- **Dokumenttypen:** Name und Beschreibung für das Modell, z. B. „Rechnung: Rechnungen, Quittungen, Kassenbons“.
- **Personen:** Name, Aliase (z. B. „Alexandra Muster“, „A. Muster“) und Hinweis (z. B. „Erwachsene, Arbeitnehmerin“).
- **Lebensbereiche:** Name und Beschreibung.
- **Korrespondenten-Ausschluss:** Muster für Sammel-Korrespondenten, die nie vorgeschlagen werden (z. B. `^o_`).
- **Status-Tags:** Namen (Standard `ai:todo`, `ai:prüfen`, `ai:fertig`, `ai:fehler`) und ob `INBOX` beim Übernehmen entfernt wird.

**Abgleich mit Paperless:**
- Jeder Eintrag ist mit einem Objekt in Paperless verknüpft (Dokumenttyp bzw. Tag).
- Fehlt es dort, zeigt der Editor „fehlt in Paperless“. Ein Klick legt es an, vorher erscheint eine Vorschau aller Änderungen.
- Vorhandene Paperless-Objekte lassen sich per Auswahl verknüpfen statt neu anzulegen, z. B. der vorhandene Tag „Steuer“.

**Sicherung und Vorbefüllung:** Export und Import als JSON. Damit lässt sich die abgestimmte Taxonomie aus der privaten Vault-Notiz einmalig einspielen, ohne dass sie im Repo landet. Im Repo liegt nur ein Beispiel mit erfundenen Daten (`config/taxonomy.example.json`), das auch der Demo-Modus nutzt.

**Neue Korrespondenten** schlägt das Modell vor. Angelegt werden sie erst, wenn du den Vorschlag übernimmst.

**Änderungen wirken sofort:** Das Schema für das Modell wird bei jedem Auftrag aus dem aktuellen Stand erzeugt. Offene Vorschläge, die einen inzwischen gelöschten Eintrag enthalten, werden als „überholt“ markiert und neu eingereiht.

## 4. Auslesen (Extraktion)

### 4.1 Eingabe
Das Modell bekommt:
- den OCR-Text, gekürzt auf etwa 6.000 Zeichen (Anfang und Ende, denn dort stehen Absender und Datum),
- den Dateinamen,
- die erlaubten Werte aus der Taxonomie mit ihren Beschreibungen,
- die Liste der vorhandenen Korrespondenten.

### 4.2 Ausgabe mit erzwungener Struktur
Das Pydantic-Modell wird **zur Laufzeit aus der Taxonomie erzeugt**. Erlaubte Werte werden zu `enum`, und Ollama erzwingt dieses JSON-Schema schon beim Erzeugen. Werte wie `{}` oder „unknwon“ sind dadurch technisch ausgeschlossen.

```python
class Extraction(BaseModel):
    document_type: Literal["Rechnung", "Bescheid", ...]
    correspondent: str                 # Name wie im Briefkopf
    correspondent_evidence: str        # wörtliches Zitat aus dem Text
    document_date: date | None
    date_evidence: str | None
    persons: list[Literal["Alex", ...]]
    area: Literal["Gesundheit", ...]
    title: str = Field(max_length=80)  # nur Inhalt, ohne Datum/Absender
```

### 4.3 Prüfen statt Glauben
Wie sicher sich ein Modell selbst einschätzt, ist kaum aussagekräftig. Deshalb wird jeder Vorschlag **überprüfbar** gemacht:

| Prüfung | Ergebnis |
|---|---|
| **Beleg-Zitat** für Korrespondent und Datum steht (unscharf) wirklich im Text | ✓ belegt / ⚠ unbelegt |
| **Datum** liegt nicht in der Zukunft und nicht vor 1950 und passt zum Beleg | ✓ / ⚠ |
| **Korrespondent:** normalisieren (ohne GmbH/AG/e. V., Satzzeichen, Groß-/Kleinschreibung), dann unscharf mit vorhandenen Namen und Aliasen abgleichen (rapidfuzz) | vorhandener Korrespondent / **neu** (Vorschlag) |
| **Personen:** Namen und Aliase kommen im Text vor | ✓ / ⚠ |
| **Titel:** Länge, kein Datum, kein Absendername doppelt | ✓ / automatisch gekürzt |

Die Prüfliste zeigt die Prüfergebnisse je Feld an und sortiert unsichere Vorschläge nach oben. Das sind auch die Daten, aus denen Phase 2 ihre Schwellen lernt.

### 4.4 Fehlerbehandlung
| Fehler | Reaktion |
|---|---|
| Antwort passt nicht zum Schema | einmal mit verkürztem Text wiederholen, danach `ai:fehler` |
| Rechner fällt während des Auftrags aus | Auftrag zurück in die Warteschlange, ohne Wartezeit, Rechner gilt als offline |
| Paperless nicht erreichbar | Wiederholung mit wachsendem Abstand (1, 5, 30 min), höchstens 5 Versuche |
| Dokument ohne Text | direkt `ai:fehler` mit Grund „kein OCR-Text“ (Vision-OCR kommt in Phase 2) |

## 5. Rechner und Scheduler

- **Rechner-Überwachung:** Alle 30 s wird jeder Rechner abgefragt: online, Version, Modelle. Das Ergebnis liegt im Speicher und wird als Ereignis an die Oberfläche geschickt.
- **Darf der Rechner arbeiten?** (Entscheidung D4) Er muss online sein, das konfigurierte Modell haben und darf nicht **pausiert** sein. Außerdem muss mindestens eine seiner Freigaben zutreffen:
  - **Zeitfenster**, z. B. `20:00–07:00`
  - **Leerlauf laut Home Assistant**: Eine Entität meldet seit mindestens *N* Minuten „nicht aktiv“, z. B. der Sensor „Active“ der HA-Companion-App auf dem Mac. Die Dauer ergibt sich aus `last_changed`.

  Optional gibt es eine **Sperre**: Eine Entität meldet „belegt“, z. B. beim Gaming-PC ein Spiel läuft (HASS.Agent). Die Sperre gilt vor allen Freigaben.
- **Pause-Schalter und Regeln je Rechner** werden in der Oberfläche gepflegt und bleiben über Neustarts erhalten.
- **Laufender Auftrag bei Ende der Freigabe:** Wirst du am Mac aktiv, wird der laufende Auftrag noch fertig gerechnet (typisch < 1 min). Danach nimmt der Rechner keine neuen an.
- **Home Assistant als Port (`AvailabilitySource`):** Der Adapter liest Zustände über die REST-API (`/api/states/<entity_id>`) mit einem Long-Lived Access Token. Ist HA nicht erreichbar, zählt nur das Zeitfenster. Das ist sicherer, als den Rechner ungefragt zu belegen.
- **Scheduler:** je Rechner ein Arbeiter mit einem Auftrag gleichzeitig, denn Ollama arbeitet ohnehin nacheinander.
  - Aufträge werden per **Lease** aus SQLite geholt (`UPDATE … RETURNING`). Abgelaufene Leases fallen automatisch zurück in die Warteschlange, z. B. nach einem Absturz.
  - Ein Auftrag je Dokument und Art ist eindeutig, ein erneutes Einreihen ist also harmlos.
- **Modell:** `PILOT_EXTRACTION_MODEL` (Start: `gemma4:26b`). Der Gaming-PC bekommt in Phase 1 nur dann Aufträge, wenn für ihn ein kleineres Modell eingetragen ist.
- **Uhr als Port (`Clock`):** Zeitfenster, Leases und Wartezeiten lassen sich so ohne echtes Warten testen.

## 6. Speicher

SQLite-Datei im Datenordner (`/data/pilot.db`, WAL-Modus), SQLAlchemy 2 (async) und Alembic-Migrationen.

| Tabelle | Inhalt |
|---|---|
| `jobs` | Dokument, Art, Status (wartend, läuft, fertig, Fehler), Versuche, Lease bis, frühester Start, letzter Fehler, Rechner |
| `suggestions` | Dokument, Auftrag, Modell, Rechner, Dauer, Stand des Dokuments beim Auslesen (`modified`), Vorschlag je Feld mit Belegen und Prüfergebnissen, Status (offen, übernommen, teilweise, verworfen, überholt) |
| `changes` | Dokument, Vorschlag, Zeitpunkt, Auslöser (Mensch/Automatik), Werte vorher und nachher, rückgängig gemacht durch |
| `host_settings` | Pause, Zeitfenster, HA-Leerlauf-Entität und Mindestdauer, HA-Sperr-Entität |
| `taxonomy_*` | Dokumenttypen, Personen (mit Aliasen), Lebensbereiche, Einstellungen; je Eintrag die verknüpfte Paperless-ID |

**Konflikte:** Vor dem Schreiben wird das Dokument neu geladen. Hat es sich seit dem Auslesen in Paperless geändert, zeigt die Prüfliste den Unterschied, statt ihn zu überschreiben. Beim Rückgängigmachen genauso: Weicht der aktuelle Wert vom damals geschriebenen ab, wird nachgefragt.

**Tags beim Übernehmen:**
- **Verwaltet und ersetzt** werden nur die Tag-Gruppen aus der Taxonomie (Personen, Lebensbereiche, Status).
- **Alle anderen Tags bleiben unangetastet.** Das Aufräumen kommt in Phase 2.

## 7. Schnittstellen (API)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/system/status` | wie bisher, dazu Zahlen der Warteschlange |
| GET | `/api/events` | Server-Sent Events: Aufträge, Vorschläge, Rechner |
| GET/PATCH | `/api/hosts`, `/api/hosts/{name}` | Rechner, Pause, Zeitfenster, HA-Regeln |
| GET/PUT | `/api/taxonomy` | Taxonomie lesen und speichern (mit Validierung) |
| GET | `/api/taxonomy/sync` | Abgleich mit Paperless: was fehlt, was ist verknüpft |
| POST | `/api/taxonomy/sync` | fehlende Objekte in Paperless anlegen |
| GET/POST | `/api/taxonomy/export`, `/api/taxonomy/import` | Sicherung als JSON |
| POST | `/api/jobs/enqueue` | einreihen: Posteingang, Tag oder Dokument-IDs |
| GET | `/api/jobs?status=` | Warteschlange, Fehler |
| POST | `/api/jobs/{id}/retry` | Fehler erneut versuchen |
| GET | `/api/suggestions?status=open` | Prüfliste |
| GET | `/api/suggestions/{id}` | Vorschlag mit aktuellem Stand des Dokuments |
| POST | `/api/suggestions/{id}/accept` | übernehmen, optional mit deinen Korrekturen je Feld |
| POST | `/api/suggestions/{id}/reject` | verwerfen, mit Grund |
| GET | `/api/documents/{id}/preview`, `/thumb` | PDF-Vorschau, vom Backend durchgereicht (der Browser hat keinen Paperless-Token) |
| GET | `/api/changes` | Verlauf |
| POST | `/api/changes/{id}/revert` | rückgängig machen |

## 8. Oberfläche

### 8.1 Prüfen

```
┌ Prüfen ─────────────────────────────── 23 offen · 71 warten · 1 Fehler ┐
│ ▸ Rechnung  Muster AG     ⚠ │ ┌──────────────┐ │ Feld        Aktuell        Vorschlag            │
│   Bescheid  Finanzamt…    ✓ │ │              │ │ Typ         Bescheinigung  [Rechnung      ▾] ✓  │
│   Brief     Stadtwerke…   ✓ │ │  PDF-        │ │ Absender    o_Sonstiges    [Muster AG ▾] neu    │
│   …                         │ │  Vorschau    │ │             „Muster AG · Hauptstr. 1“ ✓          │
│                             │ │              │ │ Datum       2026-10-07     [12.09.2025]  ✓       │
│                             │ │              │ │ Personen    –              [Alex ×] [+]          │
│                             │ │              │ │ Bereich     –              [Einkauf ▾]           │
│                             │ └──────────────┘ │ Titel       SwiftScan …    [Bürostuhl          ] │
│                             │                  │ [Enter] Übernehmen  [R] Verwerfen  [E] Bearbeiten │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Tastatur:**
  - `J`/`K` nächstes/voriges Dokument
  - `Enter` übernehmen, danach geht es automatisch weiter
  - `E` Fokus ins erste unsichere Feld
  - `R` verwerfen
  - `Z` letzte Übernahme rückgängig
  - `?` Hilfe
- **Was die Oberfläche zeigt:**
  - Geänderte Felder sind hervorgehoben, unveränderte gedämpft.
  - Belege stehen als Zitat unter dem Feld.
  - „neu“ kennzeichnet Korrespondenten, die erst angelegt würden.
- **Wenn die Liste leer ist:** „Alles geprüft“ mit der Zahl der wartenden Aufträge und dem Hinweis, welcher Rechner als Nächstes arbeitet.
- **Die PDF-Vorschau** ist in Phase 1 die eingebaute Anzeige des Browsers über die durchgereichte Vorschau. PDF.js folgt, falls nötig.

### 8.2 Verlauf
Eine Tabelle mit Zeitpunkt, Dokument und den Änderungen als Vorher→Nachher-Chips, dazu der Auslöser und „Rückgängig“. Gefiltert wird nach Dokument und Zeitraum.

### 8.3 Rechner & Modelle
Eine Karte je Rechner mit:
- Status und laufendem Auftrag,
- Durchsatz (Ø Sekunden pro Dokument),
- Freigaben (Zeitfenster, HA-Leerlauf mit aktuellem Zustand, z. B. „inaktiv seit 12 min“) und Pause-Schalter,
- Modell vorhanden ja/nein,
- einem Satz, warum der Rechner gerade (nicht) arbeitet, z. B. „Wartet: Mac wird benutzt, Zeitfenster ab 20:00“.

### 8.5 Regeln → Taxonomie
- **Drei Listen** für Dokumenttypen, Personen und Lebensbereiche. Einträge lassen sich inline bearbeiten und per Ziehen sortieren.
- **Je Eintrag:** Beschreibung bzw. Aliase und der Paperless-Status (verknüpft / fehlt / Namen weichen ab).
- **Leiste „Mit Paperless abgleichen“:** Vorschau der anzulegenden Objekte, dann Bestätigen.
- **Hinweise beim Speichern:** Die Oberfläche warnt vor doppelten Namen und vor leeren Beschreibungen, denn Beschreibungen verbessern die Ergebnisse des Modells.

### 8.4 Übersicht
- **Kennzahlen:** wartend, in Arbeit, zu prüfen, Fehler, erledigt heute.
- **Fortschritt** des Rückstands.
- **Schnellaktion** „Posteingang einreihen“.

## 9. Qualität und Tests

| Ebene | Was |
|---|---|
| Unit (Kern) | Abgleich der Korrespondenten, Normalisierung (mit Hypothesis), Plausibilitätsregeln, Schema-Erzeugung aus der Taxonomie, Tag-Zusammenführung, Freigabe-Logik (Zeitfenster über Mitternacht, Leerlauf-Dauer, Sperre, HA nicht erreichbar) |
| Speicher | Repositories gegen echte SQLite-Datei, Alembic-Migration von leer, **Lease-Konkurrenz** (zwei Arbeiter holen nie denselben Auftrag), abgelaufene Leases |
| Ablauf | Einreihen → Vorschlag → Übernehmen → Verlauf → Rückgängig, mit Attrappen für Paperless und Ollama und einer simulierten Uhr |
| Vertrag | neue Paperless-Endpunkte (Anlegen von Tags/Typen/Korrespondenten, Vorschau) und Home-Assistant-REST mit respx; Integrationstest im Container erweitert |
| API | alle neuen Routen inkl. Fehlerfälle und Konflikte |
| Frontend | Prüfen-Seite mit Tastaturbedienung, Bearbeiten, Konfliktanzeige; Verlauf mit Rückgängig; Taxonomie-Editor mit Abgleich (Vitest + MSW) |
| E2E | Playwright gegen das Backend im **Demo-Modus** (`PILOT_DEMO=1`: erfundene Dokumente, Attrappen statt Paperless und Ollama). Der Demo-Modus liefert auch Screenshots für die README. |
| Modellgüte | `paperless-pilot eval <goldstandard.json>`: misst die Genauigkeit je Feld gegen einen **privaten** Goldstandard (liegt nicht im Repo) |

Die Abdeckungsgrenzen bleiben wie in Phase 0 (Backend ≥ 90 %, Frontend ≥ 90 % Zeilen).

## 10. Umsetzungsschritte

Jeder Schritt ist ein eigener, grün getesteter Commit bzw. Pull Request:

| # | Schritt | Ergebnis |
|---|---|---|
| 1.1 | **Speicher & Warteschlange**: SQLAlchemy, Alembic, `Clock`, Jobs mit Leases und Wiederholungen | Aufträge überleben Neustarts |
| 1.2 | **Taxonomie**: Tabellen, API, Abgleich und Anlegen in Paperless, Import/Export, **Editor-Seite** | Zielordnung gepflegt und in Paperless vorhanden |
| 1.3 | **Auslesen**: Prompt, Schema aus der Taxonomie, Abgleich, Belege, Plausibilität; CLI `paperless-pilot extract <id>` (liest nur) | an ~10 echten Dokumenten auf dem Mac ausprobiert, Prompt nachgeschärft |
| 1.4 | **Rechner & Scheduler**: Überwachung, Freigaben (Zeitfenster, HA-Leerlauf, Sperre), Pause, Arbeiter, Eingang über `ai:todo`, Ereignisse (SSE), Rechner-Seite | läuft unbeaufsichtigt, nur wenn erlaubt |
| 1.5 | **Prüfen**: API, Vorschau-Proxy, Oberfläche mit Tastatur, Übernehmen mit Konflikt-Check | erster echter Nutzen |
| 1.6 | **Verlauf & Rückgängig** | Sicherheitsnetz |
| 1.7 | **Abrundung**: Übersicht, Demo-Modus, Playwright, Unraid-Anleitung, Volume `/data` | Phase 1 fertig |

**Danach:** Die Dokumente aus dem Posteingang laufen durch und werden geprüft. Die Übernahmequoten fließen in die Planung von Phase 2.

## 11. Neue Konfiguration

| Variable | Bedeutung |
|---|---|
| `PILOT_DATA_DIR` | Datenordner für SQLite (Standard `/data`) |
| `PILOT_HA_URL` | Adresse von Home Assistant (optional) |
| `PILOT_HA_TOKEN` / `PILOT_HA_TOKEN_FILE` | Long-Lived Access Token für Home Assistant |
| `PILOT_EXTRACTION_MODEL` | Modell fürs Auslesen |
| `PILOT_OLLAMA_HOSTS` | erweitert um optional `model`; Freigaben und Pause werden in der Oberfläche gepflegt |
| `PILOT_INTAKE_INTERVAL_SECONDS` | Takt des Eingangs (Standard 60) |
| `PILOT_DEMO` | Demo-Modus mit erfundenen Daten |

## 12. Entscheidungen (2026-10-30)

- **D1 – Eingang:** Ein Paperless-Workflow setzt `ai:todo`. Den Rückstand reihst du per Massenbearbeitung oder Knopf ein.
- **D2 – Andere Tags beim Übernehmen:** bleiben unangetastet. Aufräumen folgt in Phase 2.
- **D3 – Taxonomie:** wird **schon in Phase 1 in der Oberfläche** gepflegt und in der Datenbank gespeichert, mit JSON-Import/-Export.
- **D4 – Verfügbarkeit:** **Home-Assistant-Leerlauf schon in Phase 1**, zusätzlich Zeitfenster, Sperre und Pause. Wake-on-LAN folgt in Phase 2.

## 13. Voraussetzungen auf deiner Seite

- **Home Assistant:** einen Long-Lived Access Token für paperless-pilot anlegen (Profil → Sicherheit).
- **Mac:** HA-Companion-App installieren und den Sensor „Active“ aktivieren. In Home Assistant ist dafür derzeit noch keine Entität vorhanden.
- **Gaming-PC** (optional für Phase 1): Ollama im Netz freigeben, HASS.Agent mit einem Sensor für „Spiel läuft“.
- **Paperless:** Workflow „Dokument hinzugefügt → Tag `ai:todo` setzen“ anlegen, sobald Schritt 1.4 fertig ist.
