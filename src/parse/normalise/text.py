"""Text normalisation: script detection, Serbian Cyrillic->Latin, folding, language ID, relevance."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

from parse.settings import keywords

_SR_CYR2LAT = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z", "И": "I",
    "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
}
_SR_CYR2LAT.update({k.lower(): v.lower() for k, v in _SR_CYR2LAT.items()})
# Russian letters absent from the Serbian alphabet (matching only, not display transliteration).
_RU_EXTRA = str.maketrans({"й": "j", "Й": "J", "ы": "y", "Ы": "Y", "э": "e", "Э": "E", "ю": "ju", "Ю": "Ju",
                           "я": "ja", "Я": "Ja", "ь": "", "Ь": "", "ъ": "", "Ъ": "", "ё": "e", "Ё": "E",
                           "щ": "šč", "Щ": "Šč"})
_CYR = re.compile(r"[Ѐ-ӿ]")
_LAT = re.compile(r"[A-Za-zÀ-ɏ]")


def sr_cyr_to_lat(text: str) -> str:
    return "".join(_SR_CYR2LAT.get(ch, ch) for ch in text)


def cyrillic_share(text: str) -> float:
    c, l = len(_CYR.findall(text)), len(_LAT.findall(text))
    return c / (c + l) if c + l else 0.0


def fold(text: str) -> str:
    """Lower-case, Cyrillic->Latin (Serbian table), strip diacritics. Used only for matching."""
    t = sr_cyr_to_lat(text).replace("đ", "dj").replace("Đ", "Dj")
    t = t.translate(_RU_EXTRA)
    t = unicodedata.normalize("NFKD", t)
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


@lru_cache
def _detector():
    langs = [Language.ALBANIAN, Language.SERBIAN, Language.CROATIAN, Language.BOSNIAN, Language.RUSSIAN,
             Language.ENGLISH, Language.MACEDONIAN, Language.BULGARIAN]
    return LanguageDetectorBuilder.from_languages(*langs).build()


def detect_lang(text: str) -> str | None:
    """Returns one of sq, sr-Latn, sr-Cyrl, ru, en, or another ISO code. BCS variants map to sr-Latn."""
    sample = text[:2000]
    if len(sample.strip()) < 20:
        return None
    lang = _detector().detect_language_of(sample)
    if lang is None:
        return None
    cyr = cyrillic_share(sample) > 0.5
    if lang in (Language.SERBIAN, Language.CROATIAN, Language.BOSNIAN):
        return "sr-Cyrl" if cyr else "sr-Latn"
    if lang == Language.MACEDONIAN or (lang == Language.BULGARIAN and cyr):
        # Short Serbian Cyrillic text is often confused with mk/bg; Serbian-only letters settle it.
        return "sr-Cyrl" if re.search(r"[ЂђЋћЏџ]", sample) or not re.search(r"[ЃѓЌќЅѕЪъ]", sample) else lang.iso_code_639_1.name.lower()
    return {Language.ALBANIAN: "sq", Language.RUSSIAN: "ru", Language.ENGLISH: "en"}.get(
        lang, lang.iso_code_639_1.name.lower())


def to_latin(text: str, lang: str | None) -> str:
    return sr_cyr_to_lat(text) if lang == "sr-Cyrl" else text


@lru_cache
def _relevance_terms() -> tuple[str, ...]:
    return tuple(fold(t) for t in keywords()["relevance_terms"])


def is_kosovo_relevant(*texts: str | None) -> bool:
    blob = fold(" ".join(t for t in texts if t))
    # Short codes ("KiM", "FSK", "KSF", "KBS") need word boundaries; longer stems match as prefixes.
    for t in _relevance_terms():
        if len(t) <= 4:
            if re.search(rf"\b{re.escape(t)}\b", blob):
                return True
        elif t in blob:
            return True
    return False


_SLUG_STEMS = ("kosov", "kosova", "kurti", "pristin", "prishtin", "kfor", "mitrovic", "zvecan", "zvecan",
               "jarinj", "banjsk", "gazimestan", "gazivod", "ibar", "srpska-lista", "leposavi", "zubin-potok",
               "eulex", "unmik", "kbs", "fsk", "ksf", "kosmet", "kim-", "-kim", "metohij", "gracanic",
               "kosovo", "kosove", "rosu", "vidovdan")


def slug_relevant(url: str) -> bool:
    return any(s in fold(url) for s in _SLUG_STEMS)
