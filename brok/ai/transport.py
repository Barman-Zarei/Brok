"""Tiny HTTP layer (stdlib only) so providers are testable with a fake."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator, Protocol


class Transport(Protocol):
    """What providers need from an HTTP layer (the real one is :class:`UrllibTransport`; tests pass a fake)."""

    def get_json(self, url: str, headers: dict[str, str]) -> Any: ...

    def post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> Any: ...

    def stream_lines(
        self, url: str, headers: dict[str, str], body: dict[str, Any], cancel: threading.Event | None = None
    ) -> Iterator[str]: ...


class ProviderError(Exception):
    """Any failure talking to an AI provider; message is user-presentable."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _safe_url(url: str) -> str:
    """URL for error messages: no userinfo, query or fragment (API keys sometimes travel there)."""
    try:
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ""
        return f"{u.scheme}://{host}{':' + str(u.port) if u.port else ''}{u.path}"
    except ValueError:
        return "<url>"


def _abort_socket(resp: Any) -> None:
    """Unblock a thread that is waiting in ``recv`` on this response (shutdown wakes it; close alone may not)."""
    try:
        resp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001 - best effort: no socket, already closed, TLS wrapper quirks
        pass


class UrllibTransport:
    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def _open(self, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> Any:
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
            raise ProviderError(
                f"HTTP {exc.code} from {_safe_url(url)}: {detail}", retryable=exc.code >= 500 or exc.code == 429
            ) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"Cannot reach {_safe_url(url)}: {exc}") from exc

    @staticmethod
    def _decode(resp: Any) -> Any:
        try:
            return json.loads(resp.read().decode("utf-8"))
        except (OSError, http.client.HTTPException, ValueError) as exc:  # reset / truncated body / not JSON
            raise ProviderError(f"Invalid or incomplete response: {exc}") from exc

    def get_json(self, url: str, headers: dict[str, str]) -> Any:
        with self._open(url, headers, None) as resp:
            return self._decode(resp)

    def post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        with self._open(url, headers, body) as resp:
            return self._decode(resp)

    def stream_lines(
        self, url: str, headers: dict[str, str], body: dict[str, Any], cancel: threading.Event | None = None
    ) -> Iterator[str]:
        with self._open(url, headers, body) as resp:
            done = threading.Event()
            if cancel is not None:

                def _watch() -> None:  # a silent server would otherwise block cancel until the socket timeout
                    while not done.is_set():
                        if cancel.wait(0.2):
                            _abort_socket(resp)
                            return

                threading.Thread(target=_watch, daemon=True, name="brok-stream-cancel").start()
            try:
                for raw in resp:
                    if cancel is not None and cancel.is_set():
                        return
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line:
                        yield line
            except (OSError, ValueError, http.client.HTTPException) as exc:  # reset, timeout, IncompleteRead, closed
                if cancel is not None and cancel.is_set():
                    return  # we closed the socket ourselves
                raise ProviderError(f"Connection lost while streaming: {exc}") from exc
            finally:
                done.set()
