"""Dashboard language (docs/SPEC-v4.md 4.5): every UI text goes through `_()`; the English text
is the key, app/web/i18n_my.py holds the Burmese. Language per user (users.language).

    {{ _("Inbox") }}                          -> "စာဝင်ပုံး"
    {{ _("Marked {status}.", status=...) }}   -> placeholders are filled after translating
    _("Order #1001: packed.")                 -> texts made in Python (flash messages, button labels)
                                                 are matched against the {placeholder} keys, and
                                                 "A + B" / "A & B" labels part by part
Unknown texts are shown as they are (English), never an error.
"""
import re
from functools import lru_cache

from app.web.i18n_my import MY

LANGUAGES = ("my", "en")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_JOINERS = (" + ", " & ", " · ")


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    """Keys with {placeholders} as regexes, most specific (longest) first."""
    out = []
    for key, value in MY.items():
        if "{" not in key:
            continue
        parts = _PLACEHOLDER.split(key)  # text, name, text, name, ...
        rx = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>.+?)" for i, p in enumerate(parts))
        out.append((re.compile(rx + r"\Z", re.S), value))
    return sorted(out, key=lambda kv: -len(kv[0].pattern))


def _fill(text: str, values: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)


def translate(text, lang: str, **values) -> str:
    if text is None:
        return ""
    text = str(text)
    if lang != "my" or not text.strip():
        return _fill(text, values) if values else text
    if text in MY:
        return _fill(MY[text], {k: v for k, v in values.items()})
    stripped = text.strip()
    if stripped != text and stripped in MY:
        return text.replace(stripped, MY[stripped])
    for rx, target in _patterns():
        m = rx.match(text)
        if m:
            return _fill(target, {k: translate(v, lang) for k, v in m.groupdict().items()})
    for joiner in _JOINERS:  # "✅ Confirm + ask phone", "📞 Save phone & 📍 Save address"
        if joiner in text:
            parts = text.split(joiner)
            done = [translate(p, lang) for p in parts]
            if any(d != p for d, p in zip(done, parts)):
                return joiner.join(done)
    return _fill(text, values) if values else text


def translator(lang: str):
    lang = lang if lang in LANGUAGES else "en"

    def _(text, **values) -> str:
        return translate(text, lang, **values)

    return _
