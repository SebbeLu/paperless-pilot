"""Wie gut ist der OCR-Text eines Dokuments? Grundlage für die Vision-OCR (Phase 2)."""

import re

from pydantic import BaseModel, ConfigDict

# Häufige Wörter in deutschen und englischen Dokumenten. Echte Briefe bestehen zu einem guten
# Teil aus solchen Wörtern, OCR-Zeichensalat fast nie.
_WORD_LIST = """
    der die das den dem des ein eine einer einen einem eines und oder aber nicht kein keine ist
    sind war waren wird werden wurde wurden hat haben hatte hatten sein seine ihr ihre ich sie
    wir uns euch ihnen ihm mit von zu zum zur im in an am auf aus bei bis für fur nach über
    uber unter vor durch gegen ohne um als auch noch nur schon so wie wenn dass da hier dort
    sehr mehr bitte danke vielen dank sehr geehrte geehrter damen herren herr frau liebe lieber
    freundlichen grüßen grussen gruß gruss mit freundlichen ihr ihre ihren ihrem rechnung
    rechnungsnummer datum betrag summe gesamt gesamtbetrag netto brutto mwst ust steuer
    steuernummer euro eur preis menge anzahl artikel position pos leistung leistungen zahlung
    zahlbar fällig faellig konto iban bic bank kunde kunden kundennummer auftrag bestellung
    lieferung lieferschein versand adresse anschrift straße strasse telefon fax mail email
    internet seite seiten blatt nummer nr vertrag vertrags vertragsnummer versicherung beitrag
    beiträge bescheid antrag mitteilung schreiben bestätigung kündigung kuendigung frist termin
    monat jahr jahres tag tage zeitraum vom bis zum ab name vorname geburtsdatum geboren
    geburtsort ort plz postfach unterschrift gültig gueltig bitte beachten hinweis hinweise
    information informationen erhalten erhalten haben können koennen müssen muessen sollen
    möchten moechten dürfen teilen mit uns ihnen mitteilen bitten überweisen ueberweisen
    abbuchen lastschrift the and or not of to in on at for with from by as is are was were be
    been has have had this that these those it its you your we our they their he she his her a
    an invoice date amount total tax vat number customer account payment due order page dear
    sincerely regards thank thanks please name address phone valid
"""
_COMMON_WORDS = frozenset(_WORD_LIST.split())
_TOKEN = re.compile(r"\S+")
_EDGE_PUNCTUATION = "\"'„“”‚‘’»«()[]{}<>.,;:!?"
_WORD = re.compile(r"[^\W\d_]{2,}(?:-[^\W\d_]+)*")
_NUMBER = re.compile(r"[\d.,:/%€$+\-–]*\d[\d.,:/%€$+\-–]*")  # Daten, Beträge, Uhrzeiten
_NEUTRAL_SYMBOLS = frozenset("-–—•·|&/*+=#§€$%")
_VOWELS = frozenset("aeiouyäöüàáâèéêìíîòóôùúû")
_TYPICAL_CHARS_PER_PAGE = 500


class OcrQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float  # 0 = Zeichensalat oder leer, 1 = sauberer Text
    chars_per_page: float
    letter_ratio: float  # Buchstaben und Ziffern unter allen sichtbaren Zeichen
    word_ratio: float  # wortähnliche Tokens unter allen nicht-neutralen Tokens
    dictionary_ratio: float  # bekannte Wörter unter den wortähnlichen
    reasons: tuple[str, ...]  # verständliche Gründe für einen niedrigen Wert


def assess_ocr(content: str, page_count: int | None = None) -> OcrQuality:
    visible = [c for c in content if not c.isspace()]
    if not visible:
        return OcrQuality(
            score=0,
            chars_per_page=0,
            letter_ratio=0,
            word_ratio=0,
            dictionary_ratio=0,
            reasons=("kein Text",),
        )
    chars_per_page = len(visible) / max(page_count or 1, 1)
    letter_ratio = sum(c.isalnum() for c in visible) / len(visible)

    words: list[str] = []
    garbage = 0
    for raw in _TOKEN.findall(content):
        token = raw.strip(_EDGE_PUNCTUATION)
        if not token:
            garbage += 1  # nur Satzzeichen, typisch für Zeichensalat
        elif _WORD.fullmatch(token):
            if _VOWELS.intersection(token.casefold()):
                words.append(token.casefold())
            else:
                garbage += 1
        elif _NUMBER.fullmatch(token) or token in _NEUTRAL_SYMBOLS or len(token) == 1:
            continue
        else:
            garbage += 1  # Buchstaben, Ziffern und Zeichen gemischt, z. B. „130t2c26“
    judged = len(words) + garbage
    word_ratio = len(words) / judged if judged else 0.0
    dictionary_ratio = sum(w in _COMMON_WORDS for w in words) / len(words) if words else 0.0

    score = (
        0.35 * word_ratio
        + 0.35 * min(dictionary_ratio / 0.25, 1)
        + 0.15 * letter_ratio
        + 0.15 * min(chars_per_page / _TYPICAL_CHARS_PER_PAGE, 1)
    )
    reasons = tuple(
        reason
        for reason, applies in (
            ("wenig Text je Seite", chars_per_page < _TYPICAL_CHARS_PER_PAGE / 5),
            ("viele Sonderzeichen", letter_ratio < 0.8),
            ("viele Zeichenfolgen ohne Wortgestalt", word_ratio < 0.7),
            ("kaum bekannte Wörter", dictionary_ratio < 0.1),
        )
        if applies
    )
    return OcrQuality(
        score=round(score, 3),
        chars_per_page=round(chars_per_page, 1),
        letter_ratio=round(letter_ratio, 3),
        word_ratio=round(word_ratio, 3),
        dictionary_ratio=round(dictionary_ratio, 3),
        reasons=reasons,
    )
