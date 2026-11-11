"""Parse Google cookies exported from a browser.

Supports the two common export formats:

1. Netscape cookies.txt format (one cookie per line, tab-separated):
       .google.com	TRUE	/	TRUE	1730000000	__Secure-1PSID	VALUE
2. JSON array (EditThisCookie / "Get cookies.txt" style):
       [{"name": "__Secure-1PSID", "value": "...", "domain": ".google.com", ...}, ...]
"""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED = "__Secure-1PSID"
OPTIONAL = "__Secure-1PSIDTS"


class CookieError(Exception):
    pass


def _domain_score(domain: str) -> int:
    """Prefer cookies scoped to gemini.google.com, then google.com."""
    d = domain.lstrip(".").lower()
    if d == "gemini.google.com":
        return 3
    if d.endswith("google.com"):
        return 2
    if "google" in d:
        return 1
    return 0


def _best(candidates: dict[str, tuple[int, str]]) -> str | None:
    if not candidates:
        return None
    return max(candidates.values(), key=lambda t: t[0])[1]


def parse_cookies(path: str | Path) -> tuple[str, str]:
    """Return (secure_1psid, secure_1psidts) from a cookies export file."""
    path = Path(path)
    if not path.is_file():
        raise CookieError(f"Cookies file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    found: dict[str, dict[str, tuple[int, str]]] = {
        REQUIRED: {},
        OPTIONAL: {},
    }

    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        _parse_json(text, found)
    else:
        _parse_netscape(text, found)

    psid = _best(found[REQUIRED])
    if not psid:
        raise CookieError(
            f"'{REQUIRED}' not found in {path}. "
            "Log in to https://gemini.google.com, export cookies for the "
            "google.com domain (Netscape or JSON format) and retry."
        )
    psidts = _best(found[OPTIONAL]) or ""
    return psid, psidts


def _parse_netscape(text: str, found: dict) -> None:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _p, _secure, _exp, name, value = parts[:7]
        if name in found:
            score = _domain_score(domain)
            prev = found[name].get(domain)
            if prev is None or score > prev[0]:
                found[name][domain] = (score, value)


def _parse_json(text: str, found: dict) -> None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CookieError(f"Could not parse cookies file as JSON: {e}") from e
    if isinstance(data, dict):
        # Some exports wrap the array, e.g. {"cookies": [...]}
        for key in ("cookies", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise CookieError("Unexpected JSON cookies format")

    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("Name")
        value = item.get("value") or item.get("Value") or ""
        domain = item.get("domain") or item.get("Domain") or ""
        if name in found and value:
            score = _domain_score(str(domain))
            dkey = str(domain)
            prev = found[name].get(dkey)
            if prev is None or score > prev[0]:
                found[name][dkey] = (score, str(value))
