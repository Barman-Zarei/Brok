"""Tiny HTTP layer (stdlib only) so providers are testable with a fake."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Optional


class ProviderError(Exception):
    """Any failure talking to an AI provider; message is user-presentable."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class UrllibTransport:
    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def _open(self, url: str, headers: Dict[str, str], body: Optional[dict]):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = {"Content-Type": "application/json", **headers}
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)  # noqa: S310 (https/http only, set by config)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise ProviderError(f"HTTP {exc.code} from {url}: {detail}", retryable=exc.code >= 500 or exc.code == 429) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"Cannot reach {url}: {exc}") from exc

    def get_json(self, url: str, headers: Dict[str, str]) -> Any:
        with self._open(url, headers, None) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post_json(self, url: str, headers: Dict[str, str], body: dict) -> Any:
        with self._open(url, headers, body) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def stream_lines(
        self, url: str, headers: Dict[str, str], body: dict, cancel: Optional[threading.Event] = None
    ) -> Iterator[str]:
        with self._open(url, headers, body) as resp:
            for raw in resp:
                if cancel is not None and cancel.is_set():
                    return
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line:
                    yield line
