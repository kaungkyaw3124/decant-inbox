"""Cloudflare quick tunnel to the dashboard; writes the public URL to TUNNEL_URL.

Runs `cloudflared tunnel --url http://127.0.0.1:8080` (no account, no domain, no inbound
ports), passes its log through to the journal, and writes the random
https://*.trycloudflare.com address to TUNNEL_URL (git-ignored) each time it starts.
The address changes on every start. Run by the decant-tunnel systemd user unit.

Usage: .venv/bin/python -m scripts.tunnel
Read the address: cat ~/telegram-product-requests/TUNNEL_URL  (or scripts/status.sh)
"""
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from app.core.config import BASE_DIR

URL_FILE = BASE_DIR / "TUNNEL_URL"
TARGET = "http://127.0.0.1:8080"
# Quick-tunnel names are hyphenated words; this skips https://api.trycloudflare.com in errors.
URL_RE = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com")


def find_url(line: str) -> str | None:
    match = URL_RE.search(line)
    return match.group(0) if match else None


def write_url(url: str, path: Path = URL_FILE) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(url + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)  # atomic: readers never see half a file


def cloudflared_path() -> str:
    for candidate in (shutil.which("cloudflared"), Path.home() / ".local/bin/cloudflared"):
        if candidate and os.access(candidate, os.X_OK):
            return str(candidate)
    sys.exit("cloudflared not found (install the official release into ~/.local/bin)")


def main() -> None:
    URL_FILE.unlink(missing_ok=True)  # the old address is dead once cloudflared restarts
    proc = subprocess.Popen(
        [cloudflared_path(), "tunnel", "--no-autoupdate", "--url", TARGET],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
    found = False
    for line in proc.stdout:
        print(line, end="", flush=True)
        url = None if found else find_url(line)
        if url:
            write_url(url)
            found = True
            print(f"tunnel url written to {URL_FILE}", flush=True)
    code = proc.wait()
    URL_FILE.unlink(missing_ok=True)
    sys.exit(code or 1)  # always non-zero so systemd restarts it


if __name__ == "__main__":
    main()
