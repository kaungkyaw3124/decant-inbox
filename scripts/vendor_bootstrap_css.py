"""Writes app/web/static/vendor/bootstrap-5.3.8/bootstrap.subset.min.css: Bootstrap's CSS without the components
no template uses (keeps CSS + JS per page under the 400 KB of docs/SPEC-v4.15-ui-bootstrap.md).
Run again after a Bootstrap upgrade or when a template starts using one of UNUSED:
    .venv/bin/python -m scripts.vendor_bootstrap_css"""
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "app/web/static/vendor/bootstrap-5.3.8"
UNUSED = ("carousel", "accordion", "popover", "bs-popover", "tooltip", "bs-tooltip", "placeholder", "pagination",
          "page-link", "page-item", "list-group", "navbar", "form-floating", "spinner-grow", "dropdown", "dropup",
          "dropend", "dropstart", "breadcrumb", "nav-tabs", "nav-pills", "nav-underline", "ratio", "vstack", "hstack",
          "btn-group", "btn-toolbar", "input-group", "card-group", "progress", "progress-bar", "progress-stacked")
_UNUSED_CLASS = re.compile(r"\.(?:%s)(?:-[\w-]+)?(?![\w-])" % "|".join(map(re.escape, UNUSED)))
_UNUSED_KEYFRAMES = ("spinner-grow", "progress-bar-stripes", "placeholder-glow", "placeholder-wave")


def _blocks(css: str):
    """Top-level (prelude, body) pairs of minified CSS; body keeps its nested braces."""
    i = 0
    while (start := css.find("{", i)) != -1:
        depth, j = 1, start + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        yield css[i:start], css[start + 1:j - 1]
        i = j


def subset(css: str) -> str:
    out = []
    for prelude, body in _blocks(css):
        if prelude.startswith("@keyframes"):
            if prelude.split()[1] not in _UNUSED_KEYFRAMES:
                out.append(f"{prelude}{{{body}}}")
        elif prelude.startswith("@"):  # @media / @supports / @font-face ...: filter inside
            inner = subset(body) if "{" in body else body
            if inner or "{" not in body:
                out.append(f"{prelude}{{{inner}}}")
        else:
            kept = [s for s in prelude.split(",") if not _UNUSED_CLASS.search(s)]
            if kept:
                out.append(f"{','.join(kept)}{{{body}}}")
    return "".join(out)


def main() -> None:
    css = (DIR / "bootstrap.min.css").read_text()
    header = css[:css.index("*/") + 2]
    body = re.sub(r"/\*# sourceMappingURL=.*?\*/", "", css[len(header):])
    out = header + subset(body)
    (DIR / "bootstrap.subset.min.css").write_text(out)
    print(f"{len(css)} -> {len(out)} bytes")


if __name__ == "__main__":
    main()
