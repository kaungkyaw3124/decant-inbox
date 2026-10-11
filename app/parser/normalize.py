"""Text normalization shared by aliases (seed) and messages (parser).

Zawgyi -> Unicode, Burmese digits, unit variants, case and spaces. When this
changes, re-run the seed and scripts/reparse_all.py to re-normalize stored text.
"""
import re
import unicodedata

from myanmar import converter
from myanmartools import ZawgyiDetector

_ZAWGYI = ZawgyiDetector()
ZAWGYI_THRESHOLD = 0.95  # myanmar-tools' recommended cut-off

_BURMESE_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
# Longest variants first so "မီလီလီတာ" is not cut to "ml" + "လီတာ".
_UNIT_RE = re.compile(r"(?:မီလီလီတာ|မီလီ|ml\.?)", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_LINE_SPACE_RE = re.compile(r"[^\S\n]+")  # spaces/tabs, not newlines
_NEWLINES_RE = re.compile(r" *\n[\s]*")


def to_unicode(text: str) -> str:
    if _ZAWGYI.get_zawgyi_probability(text) > ZAWGYI_THRESHOLD:
        return converter.convert(text, "zawgyi", "unicode")
    return text


def normalize(text: str, keep_newlines: bool = False) -> str:
    """keep_newlines: for message text, so the parser can split items on new lines."""
    text = to_unicode(text)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_BURMESE_DIGITS)
    text = _UNIT_RE.sub("ml", text)
    text = text.lower()
    if keep_newlines:
        return _NEWLINES_RE.sub("\n", _LINE_SPACE_RE.sub(" ", text)).strip()
    return _SPACE_RE.sub(" ", text).strip()
