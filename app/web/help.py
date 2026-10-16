"""Help page (docs/SPEC-v4.md 4.5): renders docs/STAFF-GUIDE-my.md for everyone logged in.

A small Markdown subset is enough for the guide: #/##/### headings, - and 1. lists,
**bold**, `code`, paragraphs. Text is HTML-escaped first, so the guide can't inject markup."""
import re
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup

from app.web.auth import current_user
from app.web.deps import templates

router = APIRouter(dependencies=[Depends(current_user)])
GUIDE = Path(__file__).resolve().parents[2] / "docs" / "STAFF-GUIDE-my.md"


def _inline(text: str) -> str:
    text = escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def render(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    """(HTML, table of contents [(anchor, title)] of the ## headings)."""
    out: list[str] = []
    toc: list[tuple[str, str]] = []
    para: list[str] = []
    lst: str | None = None  # "ul" | "ol" while inside a list

    def close_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_list():
        nonlocal lst
        if lst:
            out.append(f"</{lst}>")
            lst = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if m := re.match(r"(#{1,3})\s+(.*)", line):
            close_para(), close_list()
            level, title = len(m.group(1)), m.group(2).strip()
            anchor = f"s{len(toc) + 1}" if level == 2 else ""
            if level == 2:
                toc.append((anchor, title))
            id_attr = f' id="{anchor}"' if anchor else ""
            out.append(f"<h{level}{id_attr}>{_inline(title)}</h{level}>")
        elif m := re.match(r"\s*(?:[-*]|(\d+)\.)\s+(.*)", line):
            close_para()
            kind = "ol" if m.group(1) else "ul"
            if lst != kind:
                close_list()
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{_inline(m.group(2))}</li>")
        elif not line.strip():
            close_para(), close_list()
        else:
            close_list()
            para.append(line.strip())
    close_para(), close_list()
    return "\n".join(out), toc


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    body, toc = render(GUIDE.read_text(encoding="utf-8"))
    return templates.TemplateResponse(request, "help.html", {"body": Markup(body), "toc": toc})
