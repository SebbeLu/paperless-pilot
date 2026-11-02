# Phase 2 – Vision-OCR: Plan

Stand: 2026-11-02 · Status: Schritte 2.1 bis 2.4 umgesetzt · Grundlage: [konzept.md](konzept.md), Abschnitt 6, Schritt 2

## 1. Ziel

Paperless erkennt Text mit Tesseract. Bei Ausweisen, Fotos, Kassenbons und Scans mit Mustern oder Stempeln kommt dabei oft Zeichensalat heraus. Der Bestand hat rund 80 solcher Dokumente. Darunter leiden die Suche in Paperless und das Auslesen durch paperless-pilot.

Am Ende dieses Schritts gilt:

1. paperless-pilot **bewertet** den Text jedes Dokuments. Ist er schlecht, schreibt ein Vision-Modell die Seiten vom Bild ab, **bevor** ausgelesen wird.
2. Der neue Text landet als Teil des Vorschlags in **Prüfen**, mit Gegenüberstellung alt/neu und Warnungen an verdächtigen Stellen.
3. Erst wenn du übernimmst, wird das **Inhaltsfeld in Paperless ersetzt**. Der alte Text steht im Verlauf, „Rückgängig“ stellt ihn wieder her.
4. Ein KI-Knopf **„Text neu erkennen“** stößt dasselbe für beliebige Dokumente an, in Prüfen und im Verlauf, auch für markierte.

**Nicht Teil dieses Schritts:**
- die Textebene der Archiv-PDF ändern: Paperless durchsucht das Inhaltsfeld, die PDF bleibt unangetastet;
- Handschrift gezielt erkennen;
- automatische Übernahme ohne Prüfung (kommt mit „gelerntem Vertrauen“).

## 2. Probelauf (2026-11-02)

Getestet mit einem Ausweis-Scan (2 Seiten), gemma4:26b auf dem Mac, Seiten mit 200 dpi gerendert:

| Beobachtung | Folge für den Plan |
|---|---|
| Feldnamen, Namen, Daten, Orte und Behörde fehlerfrei, wo Tesseract nur Bruchstücke lieferte | Ansatz trägt |
| 18 s und 6 s je Seite bei sehr großen Bildern (über 5000 px) | Bilder vorher auf etwa 2000 px lange Seite verkleinern |
| Eine **Unterschrift** wurde als Name „abgeschrieben“ | Prompt: Unterschriften und Stempel nur als `[Unterschrift]` / `[Stempel]` |
| Die maschinenlesbare Zone (MRZ) war verdreht und teils erfunden | MRZ-Prüfziffern nachrechnen, sonst Warnung |
| Endlose `<<<`-Kette am Seitenende | Antwortlänge begrenzen, Wiederholungen abschneiden und melden |
| „ß“ als „B“ gelesen | Hinweis im Prompt; Gegenprüfung findet so etwas nicht, daher Vergleichsansicht |

**Fazit:** Das Modell liest deutlich besser als Tesseract, erfindet aber an Stellen, die es nicht lesen kann. Deshalb gilt wie überall in paperless-pilot: **prüfen statt glauben**, und nichts geht ohne deine Freigabe nach Paperless.

## 3. Ablauf

```
Auftrag „auslesen“
  └─ Textqualität bewerten
       ├─ gut ─────────────────────────────▶ auslesen wie bisher
       └─ schlecht, noch kein erkannter Text
            └─ Auftrag „Text erkennen“ (nur Rechner mit Vision-Modell)
                 ├─ Original laden, Seiten rendern und verkleinern
                 ├─ je Seite abschreiben lassen
                 ├─ Schutzregeln anwenden (Abschnitt 6)
                 └─ erkannten Text speichern → Auftrag „auslesen“ mit dem neuen Text
Prüfen (ein Vorschlag je Dokument)
  ├─ Metadaten wie bisher
  └─ Abschnitt „Text“: alt/neu, Warnungen, Kästchen „Erkannten Text übernehmen“
Übernehmen ─▶ PATCH an Paperless: Metadaten und, falls angehakt, Inhalt → Verlauf
```

**Ein Vorschlag je Dokument:** Text und Metadaten kommen zusammen in eine Karte. Du prüfst ein Dokument also einmal, nicht zweimal. Ist der erkannte Text unbrauchbar, nimmst du den Haken weg und übernimmst nur die Metadaten.

## 4. Textqualität bewerten

Reine Funktion im Domain-Kern, ohne Modell und ohne Netz:

- **Zeichen je Seite:** sehr wenig Text bei mehreren Seiten spricht für einen schlechten Scan.
- **Buchstabenanteil:** Anteil von Buchstaben und Ziffern an allen Zeichen ohne Leerraum.
- **Wortanteil:** Anteil der Tokens, die wie Wörter aussehen: mindestens drei Buchstaben, ein Vokal, keine Sonderzeichen mittendrin.
- **Wörterbuchtreffer:** Anteil der Wörter, die in einer eingebauten Liste häufiger deutscher und englischer Wörter stehen.

Daraus ergibt sich ein Wert von 0 bis 1. Unter der Schwelle (`PILOT_OCR_QUALITY_THRESHOLD`) gilt der Text als schlecht.

**Abweichung vom Konzept:** Paperless liefert den Text als Ganzes ohne verlässliche Seitengrenzen. Bewertet wird deshalb das **Dokument**, nicht die einzelne Seite. Abgeschrieben werden alle Seiten bis `PILOT_VISION_MAX_PAGES`. Längere Dokumente bekommen eine Warnung und werden nicht automatisch abgeschrieben, per Knopf aber schon.

**Kalibrieren:** Der Befehl `paperless-pilot ocr-score` bewertet alle Dokumente nur lesend und zeigt die Verteilung und die schlechtesten 30. Die Schwelle legen wir danach gemeinsam fest.

## 5. Seiten rendern und abschreiben

- **Quelle:** die Originaldatei aus Paperless (`/api/documents/<id>/download/?original=true`). Bilder (JPEG, PNG, TIFF) werden direkt verwendet, PDFs mit `pypdfium2` gerendert. Das ist ein reines Python-Paket mit fertigen Wheels und braucht keine Systembibliotheken im Container.
- **Größe:** 200 dpi, danach auf höchstens 2000 px lange Seite verkleinern (`Pillow`), als PNG.
- **Modell:** `PILOT_VISION_MODEL` (Start: `gemma4:26b`). Der Ollama-Anschluss kann Bilder schon mitschicken.
- **Prompt (Kern):** Text wörtlich und zeilenweise abschreiben, nichts ergänzen, nichts korrigieren. Unleserliches als `[…]`, Unterschriften als `[Unterschrift]`, Stempel als `[Stempel]`, Fotos als `[Bild]`.
- **Ausgabe:** je Seite Freitext, nicht als JSON-Schema. Strukturierte Ausgabe bringt beim Abschreiben nichts und verleitet zum Kürzen. Die Seiten werden mit Leerzeile und `--- Seite N ---` verbunden.
- **Rechner:** Die Rechner-Überwachung liest zusätzlich die Fähigkeiten des Modells (`/api/show` → `capabilities`). Aufträge „Text erkennen“ gehen nur an Rechner, deren Modell `vision` kann. In der Oberfläche unter *Rechner & Modelle* steht das sichtbar dabei.

## 6. Schutzregeln (prüfen statt glauben)

Jede Regel erzeugt eine Warnung am Vorschlag, wie die bisherigen Prüfungen:

| Regel | Prüfung | Bei Verstoß |
|---|---|---|
| Wiederholung | dieselbe Zeile mehr als dreimal hintereinander oder ein Zeichen mehr als 40-mal am Stück; Antwort je Seite auf `num_predict` begrenzt | abschneiden, Warnung „Wiederholung abgeschnitten“ |
| Zahlen nur im neuen Text | Tokens mit Ziffern (Daten, Beträge, Nummern) werden normalisiert und im alten Text unscharf gesucht | Warnung mit Liste, in der Vergleichsansicht markiert |
| IBAN | Prüfziffer nach ISO 13616 (Modulo 97) | Warnung „IBAN-Prüfziffer falsch“ |
| MRZ (Ausweise, Pässe) | Prüfziffern nach ICAO 9303 | Warnung „Maschinenlesbare Zone unsicher“ |
| Datum | gültiges Kalenderdatum | Warnung |
| Länge | neuer Text deutlich kürzer als der alte, bei gutem Wortanteil des alten | Warnung „Text fehlt womöglich“ |
| Qualität | Qualitätswert neu ≤ alt | kein Vorschlag für den Text, nur Hinweis |

Mit Warnungen ist das Kästchen „Erkannten Text übernehmen“ **nicht** vorausgewählt. Ohne Warnungen ist es angehakt.

## 7. Speicher und Schnittstellen

- **Vorschlag:** `MetadataValues` bekommt das Feld `content`. Im Vorschlag stehen damit alter und neuer Text, dazu der Qualitätswert vorher/nachher, Modell, Rechner und Dauer.
- **Verlauf:** Eine Änderung speichert den alten Inhalt im Vorher-Stand. „Rückgängig“ schreibt ihn zurück, mit der üblichen Konfliktprüfung.
- **Datenbank:** neue Auftragsart `transcribe`, eine Alembic-Migration für die Qualitätswerte am Vorschlag.
- **Paperless:** `PATCH /api/documents/<id>/` mit `content`. Der Integrationstest gegen echtes Paperless in der CI prüft, dass Paperless den Suchindex danach aktualisiert.
- **API:**
  - `POST /api/documents/transcribe` mit `ids`: Text neu erkennen (Verlauf, Prüfen, markierte);
  - `GET /api/documents/<id>/quality`: Qualitätswert und Begründung;
  - `POST /api/suggestions/{id}/accept` nimmt `content` wie die übrigen Werte entgegen.

## 8. Oberfläche

- **Prüfen, Abschnitt „Text“** unter dem Formular:
  - Kennzeichen „neu erkannt“ mit Qualitätswert alt → neu und dem KI-Symbol;
  - Kästchen „Erkannten Text übernehmen“, Warnungen darunter;
  - Knopf **„Vergleichen“**: alt und neu nebeneinander, Unterschiede auf Wortebene hervorgehoben, Warnstellen gelb.
- **KI-Knopf „Text neu erkennen“** (✨): auf der Prüfen-Karte, in der Markier-Leiste von Prüfen und im Verlauf. Er reiht „Text erkennen“ mit Vorrang ein, danach folgt das Auslesen.
- **Übersicht:** Kachel „schwacher Text: N Dokumente“ mit Knopf „Alle einreihen“.
- **Rechner & Modelle:** Kennzeichen „Vision“ je Modell.
- **Tastatur:** `T` öffnet bzw. schließt den Vergleich.

## 9. Umsetzungsschritte

Je Schritt ein Commit, jeweils mit Tests und grüner CI.

| Schritt | Inhalt | Prüfung |
|---|---|---|
| 2.1 | Qualitätsbewertung im Domain-Kern, Befehl `ocr-score` | mit dir: Verteilung ansehen, Schwelle festlegen |
| 2.2 | Rendern, Abschreiben, Schutzregeln; Befehl `paperless-pilot transcribe <id>` schreibt nichts | Probelauf an 10 echten schwachen Dokumenten, Zeit je Seite messen |
| 2.3 | Auftragsart `transcribe`, Vision-Fähigkeit der Rechner, Scheduler-Zuordnung, Einbau vor dem Auslesen | Flow-Tests mit Fake-Rechnern |
| 2.4 | `content` in Vorschlag und Verlauf, Übernehmen und Rückgängig, Migration | Integrationstest gegen echtes Paperless (Inhalt und Suche) |
| 2.5 | Oberfläche: Abschnitt „Text“, Vergleich, KI-Knöpfe, Kachel, Vision-Kennzeichen | Vitest, Browser-Prüfung im Demo-Modus |
| 2.6 | Demo-Daten, Playwright-Test, README | E2E grün |

## 10. Neue Konfiguration

| Variable | Bedeutung | Start |
|---|---|---|
| `PILOT_VISION_MODEL` | Modell zum Abschreiben | `gemma4:26b` |
| `PILOT_OCR_QUALITY_THRESHOLD` | darunter gilt der Text als schlecht | 0.68 (Abschnitt 13) |
| `PILOT_VISION_MAX_PAGES` | Höchstzahl Seiten beim automatischen Abschreiben | 8 |
| `PILOT_VISION_DPI` | Auflösung beim Rendern | 200 |

## 11. Entscheidungen (2026-11-02)

- **V1 – Ziel des Textes:** Der erkannte Text wird als **Vorschlag** geprüft und nach Übernahme ins Inhaltsfeld von Paperless geschrieben. Der alte Text bleibt im Verlauf, Rückgängig ist möglich.
- **V2 – Auslöser:** **automatisch** bei schlechter Textqualität vor dem Auslesen, zusätzlich per KI-Knopf „Text neu erkennen“.
- **V3 – Bewertung je Dokument** statt je Seite, weil Paperless keine verlässlichen Seitengrenzen liefert.
- **V4 – Ein Vorschlag je Dokument:** Text und Metadaten werden zusammen geprüft.

## 12. Offene Punkte

- Schwelle für die Textqualität: Vorschlag 0.68 (Abschnitt 13), deine Bestätigung steht aus.
- Ob ein kleineres Vision-Modell auf dem Gaming-PC reicht, etwa aus der Qwen-VL-Familie (Benchmark in Phase 2).
- Unabhängig davon auf deiner Seite: `PAPERLESS_OCR_LANGUAGE=deu+eng` in Paperless prüfen. Das verbessert den Grundtext neuer Dokumente.

## 13. Umsetzung

### Schritt 2.1 – Textqualität bewerten (2026-11-02)

`assess_ocr` im Domain-Kern und der Befehl `paperless-pilot ocr-score`, der nur liest. Gewichtung des Werts: Wortanteil 35 %, bekannte Wörter 35 % (voll ab 25 % Trefferquote), Buchstabenanteil 15 %, Textmenge je Seite 15 % (voll ab 500 Zeichen).

**Lauf gegen den echten Bestand** (714 Dokumente):

| Wert | 0–0.1 | 0.1–0.5 | 0.5–0.6 | 0.6–0.7 | 0.7–0.8 | 0.8–0.9 | 0.9–1 |
|---|---|---|---|---|---|---|---|
| Dokumente | 22 | 14 | 11 | 24 | 50 | 169 | 424 |

Unter 0.68 liegen **60 Dokumente**. Das passt zu den rund 80 aus der ersten Bestandsaufnahme, die noch gröber gezählt hat.

**Gefundene Fehlerarten** – alle löst das Abschreiben vom Bild:

| Art | Beispiel | Wert |
|---|---|---|
| kein Text | Fotos, Bilder, Ultraschall | 0 |
| fast leere Textebene | PDFs mit Textebene, aber nur 2 Zeichen je Seite; Paperless hat deshalb kein OCR gemacht | 0 |
| kaputte Zeichentabelle im PDF | Buchstaben um drei Stellen verschoben („OHGLJ“ statt „ledig“) oder ganz fremde Zeichen | 0.2–0.4 |
| gesperrte Schrift | „R e c h n u n g“ – lesbar, aber nicht durchsuchbar | 0.3 |
| Zeichensalat | Ausweise, Muster im Hintergrund, Thermopapier | 0.4–0.65 |
| Seite auf dem Kopf erkannt | „Legnıd“, „aqj jap“ – Tesseract liest die gedrehte Seite rückwärts | 0.6–0.67 |

**Grenzbereich:** Gehaltsabrechnungen (viele Tabellen und Kürzel) liegen bei 0.68–0.73, ausländische Kassenbons um 0.64. Daher der Vorschlag **0.68**: Er fängt die Seiten auf dem Kopf und lässt die Gehaltsabrechnungen in Ruhe. Ein ausländischer Bon wird zwar abgeschrieben, sein Text bleibt aber nur ein Vorschlag.

**Für Schritt 2.2:** Prüfen, ob das Vision-Modell auf dem Kopf stehende Seiten selbst richtig liest. Sonst wird die Seite vor dem Rendern gedreht.

### Schritt 2.2 – Abschreiben (2026-11-02)

- `PageRenderer` rendert PDFs mit `pypdfium2`, liest Bilder und mehrseitige TIFFs mit `Pillow` und verkleinert auf 2000 px.
- `TranscriptionService` lädt die Originaldatei, schreibt jede Seite einzeln ab und wendet die Schutzregeln an.
- `paperless-pilot transcribe <id>` zeigt Text, Qualität vorher → nachher, Dauer und Warnungen, ohne zu schreiben.
- Die Vorschau-Schnittstelle bleibt auf Vorschau und Miniatur beschränkt; die Originaldatei holt nur der Dienst selbst.

**Seiten aufrichten:**
- Das Vision-Modell liest Seiten, die auf dem Kopf stehen, zwar, erfindet dabei aber mehr, etwa einen falschen Fachbereich im Briefkopf.
- Ob eine Seite auf dem Kopf steht, erkennt das Modell selbst nicht zuverlässig.
- Deshalb fragt der Dienst Tesseract (nur Lageerkennung, `--psm 0`). Die Seite wird nur gedreht, wenn Tesseract sicher ist und die gedrehte Seite danach auch für Tesseract aufrecht steht. Gefaltete Blätter, deren eine Hälfte auf dem Kopf steht, bleiben so unverändert.
- Das Container-Image enthält dafür `tesseract-ocr`. Fehlt Tesseract, etwa bei der Entwicklung, wird nicht gedreht.

**Probelauf an 10 echten Dokumenten** (gemma4:26b, Mac M4 Pro), je eines pro Fehlerart:

| Art | Seiten | Qualität vorher → nachher | Dauer |
|---|---|---|---|
| Ausweis | 2 | 0.63 → 0.82 | 14 s |
| Brief mit Seiten auf dem Kopf | 8 | 0.64 → 0.91 | 110 s |
| gefaltetes Zertifikat | 1 | 0.67 → 0.96 | 12 s |
| kaputte Zeichentabelle | 6 | 0.38 → 0.95 | 129 s |
| fremde Zeichen | 8 | 0.24 → 0.97 | 114 s |
| gesperrte Schrift | 2 | 0.29 → 0.80 | 22 s |
| fast leere Textebene | 1 | 0.00 → 0.94 | 16 s |
| Kassenbon (ausländisch) | 2 | 0.52 → 0.71 | 18 s |
| Bescheinigung | 1 | 0.50 → 0.92 | 13 s |
| Rezept | 2 | 0.56 → 0.80 | 9 s |

Alle zehn sind deutlich besser lesbar. Im Schnitt dauert das 10–20 s je Seite; die 60 Dokumente unter der Schwelle brauchen damit grob eine Stunde Rechenzeit auf dem Mac.

**Was der Probelauf geändert hat:**

| Beobachtung | Folge |
|---|---|
| Das Modell hängt sich in Schleifen auf („[Bild] [Bild] …“) und schreibt bis zur Längengrenze weiter: 95 s für eine Seite | Antwort wird gestreamt und abgebrochen, sobald sie sich wiederholt (`looks_stuck`): 95 s → 16 s, beim 8-Seiten-Brief 446 s → 110 s |
| Wortgruppen-Schleifen innerhalb einer Zeile | werden auf drei Wiederholungen gekürzt; erst ab acht Wiederholungen, weil leere Tabellenzellen sich auch echt wiederholen |
| Tabellen kommen als Markdown mit Trennzeilen (`\| :--- \|`) | Trennzeilen werden entfernt |
| Verstümmelte Ausweiszeile mit 60 Zeichen wurde nicht als solche erkannt | jede Zeile ab 20 Zeichen aus `A–Z`, `0–9` und `<` gilt als MRZ und wird geprüft |
| Zahlen, die das Modell gelesen hat, die Tesseract aber gar nicht erkannt hatte (z. B. eine Zugangsnummer auf dem Ausweis) | werden gemeldet – das ist gewollt: genau dort muss man hinsehen |
| Bei Seiten auf dem Kopf meldet die Zahlen-Prüfung fast alles, weil der alte Text nur Zeichensalat enthält | bleibt vorerst so; in der Oberfläche (Schritt 2.5) werden die Zahlen im Vergleich markiert statt als lange Liste gezeigt |

### Schritt 2.3 – Einbau in Warteschlange und Rechner (2026-11-02)

- **Neue Auftragsart `transcribe`.** Ein Auftrag „auslesen“ prüft zuerst die Textqualität. Liegt sie unter der Schwelle, reiht er „abschreiben“ mit derselben Priorität ein und ist erledigt. Nach dem Abschreiben folgt ein neuer Auftrag „auslesen“.
- **Nicht noch einmal abschreiben,** wenn es für das Dokument schon eine Abschrift gibt, wenn der letzte Versuch endgültig gescheitert ist oder wenn kein Rechner Bilder versteht. Dann wird wie bisher mit dem OCR-Text von Paperless ausgelesen.
- **Abschrift speichern:** Tabelle `transcriptions`, je Dokument nur die neueste (Migration 0003).
- **Auslesen mit der Abschrift:** Das Modell bekommt die Abschrift statt des OCR-Texts, und die Belegzitate werden gegen sie geprüft. Ist die Abschrift nicht besser als der OCR-Text, bleibt es beim OCR-Text.
- **In Paperless ändert sich dabei nur der Status-Tag.** Der Inhalt wird erst mit der Übernahme geschrieben (Schritt 2.4).
- **Rechner:** Die Rechner-Überwachung fragt einmal je Rechner und Modell `/api/show` nach den Fähigkeiten und merkt sie sich. Aufträge „abschreiben“ bekommen nur Rechner, deren Vision-Modell (`PILOT_VISION_MODEL`) installiert ist und `vision` kann. Ist ein Rechner offline, gilt der letzte bekannte Stand.
- **Zeit:** Ein Auftrag „abschreiben“ verlängert seine Lease auf `PILOT_LLM_TIMEOUT_SECONDS` × `PILOT_VISION_MAX_PAGES`, damit lange Dokumente nicht einem zweiten Rechner zufallen.
- **Fehler:** Ist der Rechner weg, geht der Auftrag ohne Fehlversuch zurück in die Warteschlange. Lässt sich die Datei nicht lesen oder scheitert das Abschreiben endgültig, wird mit dem OCR-Text ausgelesen.

### Schritt 2.4 – Text übernehmen und rückgängig machen (2026-11-02)

- **Am Vorschlag:** `proposed.content` enthält die Abschrift. Dazu kommt `transcription` mit Herkunft (Modell, Rechner, Dauer), Seitenzahl, aufgerichteten und ausgelassenen Seiten, Qualität vorher/nachher und Warnungen (Migration 0004). Der bisherige Text wird nicht doppelt gespeichert, er steht in Paperless.
- **Übernehmen:** Ist `content` in den übernommenen Werten gesetzt, schreibt der PATCH an Paperless den Inhalt mit. Der Verlauf hält dann den alten und den neuen Text fest. Fürs Lernen aus Korrekturen zählt der Text nicht.
- **Rückgängig** schreibt den alten Text zurück. Hat jemand den Text inzwischen in Paperless geändert, meldet es einen Konflikt („Inhalt“), wie bei den übrigen Feldern.
- **Nur auf ausdrücklichen Wunsch:**
  - Die Prüfseite schickt den Text bis Schritt 2.5 nicht mit.
  - Die Sammel-Übernahme schreibt ihn nur mit `with_content` und nur bei Abschriften ohne Warnungen.
  - So landet kein Text in Paperless, den du nicht gesehen hast.
- **Gegen echtes Paperless 3.2.1 geprüft (CI):** Die Originaldatei lässt sich laden, der Inhalt lässt sich per PATCH ersetzen, und die Volltextsuche findet danach den neuen Text.
