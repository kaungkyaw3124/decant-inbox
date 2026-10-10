"""Text normalization shared by aliases (seed) and messages (parser).

Phase 1 covers digits, units, case and spaces. Phase 3 adds Zawgyi -> Unicode
(myanmar-tools); after that, re-run the seed and reparse_all to re-normalize.
"""
import re
import unicodedata

_BURMESE_DIGITS = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
# Longest variants first so "မီလီလီတာ" is not cut to "ml" + "လီတာ".
_UNIT_RE = re.compile(r"(?:မီလီလီတာ|မီလီ|ml\.?)", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_BURMESE_DIGITS)
    text = _UNIT_RE.sub("ml", text)
    text = text.lower()
    return _SPACE_RE.sub(" ", text).strip()
