"""Dashboard language (docs/SPEC-v4.md 4.5): English keys, Burmese translations.

Templates call t("English text") or t("Order #{no}", no=...). English users see the key.
Strings built in Python (flash notes, errors, button labels) are translated at display time:
t(text) tries the exact text, then the patterns ("{name}" parts are captured and translated
again if they are known words), then sentence by sentence. Unknown text stays as it is.
Codes (intents, statuses) go through code(): "ask_price" -> "ဈေးမေး" / "ask price".
"""
import re
from functools import lru_cache

from markupsafe import Markup

from app.models.users import LANGUAGES
from app.web.i18n_my import CODES, MY

DEFAULT = "my"  # login page and new staff
_NAME = re.compile(r"\{(\w+)\}")
_SENTENCE = re.compile(r"(?<=[.!?။])\s+")


def _compile(key: str) -> re.Pattern:
    parts = _NAME.split(key)  # literal, name, literal, name, ...
    # a captured part never spans a sentence end, so "Order #1: Packed. Undo for 60 s." splits into sentences
    return re.compile("".join(re.escape(p) if i % 2 == 0 else rf"(?P<{p}>(?:(?![.!?။]\s).)+?)"
                              for i, p in enumerate(parts)) + r"\Z", re.S)


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    keys = [k for k in MY if _NAME.search(k) and len(_NAME.sub("", k).strip()) >= 3]
    keys.sort(key=lambda k: len(_NAME.sub("", k)), reverse=True)  # most literal text first
    return [(_compile(k), MY[k]) for k in keys]


def _word(value: str) -> str:
    """A captured part ("{status}" in "Order #1001 is {status}.") is translated too if known."""
    return _one(value) or CODES.get(value) or value


def _one(text: str) -> str | None:
    if text in MY:
        return MY[text]
    for pattern, target in _patterns():
        if m := pattern.match(text):
            return target.format(**{k: _word(v) for k, v in m.groupdict().items()})
    return None


def translate(text, lang: str, /, **values) -> str:
    if text is None:
        return ""
    text = str(text)
    if lang != "my":
        return text.format(**values) if values else text
    if values:
        return MY.get(text, text).format(**values)
    if not text.strip():
        return text
    found = _one(text) if text.strip() == text else None
    if found is not None:
        return found
    parts = _SENTENCE.split(text.strip())
    if len(parts) > 1:
        return " ".join(_one(p) or p for p in parts)
    return text


def code(value, lang: str) -> str:
    """An enum value (intent, status, kind) for display."""
    if value is None:
        return ""
    value = str(value)
    if lang == "my" and value in CODES:
        return CODES[value]
    return value.replace("_", " ")


def _html(text: str) -> Markup:
    """Escape like a template literal: <, >, & and " (attributes), but keep apostrophes readable."""
    return Markup(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&#34;"))


def for_lang(lang: str):
    """The template helpers bound to one language: t("literal", **values) for template text,
    tr(value) for text made in Python (escaped like any value), code(value) for enum values."""
    lang = lang if lang in LANGUAGES else DEFAULT

    def t(text, /, **values) -> Markup:
        if values:  # a template literal with {names}: Markup.format escapes the values
            template = MY.get(str(text), str(text)) if lang == "my" else str(text)
            return _html(template).format(**values)
        return _html(translate(text, lang))

    def tr(text) -> str:
        return translate(text, lang)

    return t, tr, (lambda value: code(value, lang))
