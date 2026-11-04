from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "polymarket-btc-study/0.1 (research; contact-local)"


def get_json(base: str, params: dict[str, Any], retries: int = 5) -> Any:
    url = f"{base}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if isinstance(exc, HTTPError) and exc.code in (400, 404):
                raise
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"API request failed after {retries} attempts: {url}") from last


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())
