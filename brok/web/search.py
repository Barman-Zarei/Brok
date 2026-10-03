"""Web research abstraction: search providers + safe page fetch (SSRF-guarded)."""

from __future__ import annotations

import ipaddress
import re
import socket
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


def is_public_url(url: str) -> bool:
    """Reject non-http(s) and private/loopback/link-local targets (SSRF guard)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


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
        with (opener or urllib.request.urlopen)(req, timeout=20) as r:  # noqa: S310
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
