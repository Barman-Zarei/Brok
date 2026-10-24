"""Web research abstraction: search providers + safe page fetch (SSRF-guarded)."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import quote, urlparse

from ..agent.tools import Confirm, Risk, ToolError, ToolRegistry, ToolSpec
from ..ai.transport import Transport


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class BraveSearchProvider(SearchProvider):
    name = "brave"

    def __init__(self, key_resolver: Callable[[], str], transport: Transport | None = None) -> None:
        from ..ai.transport import UrllibTransport

        self._key, self.t = key_resolver, transport or UrllibTransport(20)

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        import os

        key = os.environ.get("BRAVE_API_KEY", "") or self._key()
        if not key:
            raise ToolError("web search key missing: set BRAVE_API_KEY")
        data = self.t.get_json(
            f"https://api.search.brave.com/res/v1/web/search?q={quote(query)}&count={limit}",
            {"X-Subscription-Token": key, "Accept": "application/json"},
        )
        return [
            SearchResult(r.get("title", ""), r.get("url", ""), r.get("description", ""))
            for r in data.get("web", {}).get("results", [])[:limit]
        ]


def _ip_is_public(addr: str) -> bool:
    """True only for a globally routable unicast address (not private/loopback/link-local/CGNAT/reserved/multicast)."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])  # drop an IPv6 scope id such as fe80::1%eth0
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)  # ::ffff:127.0.0.1 is loopback, but only newer Pythons say so
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def is_public_url(url: str) -> bool:
    """Reject non-http(s) and private/loopback/link-local targets (SSRF guard)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except OSError:
        return False
    return bool(infos) and all(_ip_is_public(str(info[4][0])) for info in infos)


class _GuardedConnect:
    """Check the address we actually connected to, before any request is sent.

    The DNS check in :func:`is_public_url` is separate from the connect (a rebinding DNS server can answer a public
    address first and 127.0.0.1 second), so the peer is verified on the live socket as well.
    """

    def connect(self) -> None:
        super().connect()  # type: ignore[misc]
        peer = str(self.sock.getpeername()[0])  # type: ignore[attr-defined]
        if not _ip_is_public(peer):
            self.sock.close()  # type: ignore[attr-defined]
            raise OSError(f"refusing to connect to non-public address {peer}")


class _GuardedHTTPConnection(_GuardedConnect, http.client.HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnect, http.client.HTTPSConnection):
    pass


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: Any) -> Any:
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: Any) -> Any:
        kwargs: dict[str, Any] = {"context": getattr(self, "_context", None)}
        if hasattr(self, "_check_hostname"):
            kwargs["check_hostname"] = self._check_hostname
        return self.do_open(_GuardedHTTPSConnection, req, **kwargs)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects on its own: a public page could bounce us to http://169.254.169.254/ or localhost."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not is_public_url(newurl):
            raise urllib.error.URLError(f"redirect to a non-public URL refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _guarded_open(req: Any, timeout: float = 20) -> Any:
    handlers: list[Any] = [_GuardedRedirect]
    if not urllib.request.getproxies():  # behind a proxy the peer is the proxy; redirect targets are still checked
        handlers += [_GuardedHTTPHandler, _GuardedHTTPSHandler]
    return urllib.request.build_opener(*handlers).open(req, timeout=timeout)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self._skip += tag in ("script", "style", "noscript")

    def handle_endtag(self, tag: str) -> None:
        self._skip -= (tag in ("script", "style", "noscript")) and self._skip > 0

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(p.parts))


def fetch_page(url: str, max_chars: int = 8000, opener: Callable[..., Any] | None = None) -> str:
    if not is_public_url(url):
        raise ToolError("refusing to fetch non-public or non-http(s) URL")
    req = urllib.request.Request(url, headers={"User-Agent": "Brok"})
    try:
        with (opener or _guarded_open)(req, timeout=20) as r:
            raw = r.read(1_000_000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"fetch failed: {exc}")
    return html_to_text(raw)[:max_chars]


def register_web_tools(reg: ToolRegistry, provider: SearchProvider | None) -> None:
    S = {"type": "string"}

    def web_search(query: str) -> str:
        if provider is None:
            raise ToolError("web search is not configured (offline); continue with local knowledge")
        res = provider.search(query)
        return "\n".join(f"{r.title}\n{r.url}\n{r.snippet}\n" for r in res) or "no results"

    reg.register(
        ToolSpec(
            "web_search",
            "Search the web (prefer official docs; do not guess versions).",
            {"type": "object", "properties": {"query": S}, "required": ["query"]},
            Risk.LOW,
            Confirm.NEVER,
            web_search,
        )
    )
    reg.register(
        ToolSpec(
            "fetch_url",
            "Fetch a public web page as text.",
            {"type": "object", "properties": {"url": S}, "required": ["url"]},
            Risk.MEDIUM,
            Confirm.CONFIGURABLE,
            fetch_page,
        )
    )
