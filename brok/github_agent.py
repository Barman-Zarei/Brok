"""GitHub REST client for the agent. Reads are free; every mutation goes through the approval gate."""

from __future__ import annotations

import os
from typing import Any, Callable

from .agent.tools import Confirm, Risk, ToolError, ToolRegistry, ToolSpec
from .ai.transport import ProviderError, UrllibTransport

API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token_resolver: Callable[[], str] | None = None, transport=None, base: str = API) -> None:
        self._resolver, self.t, self.base = token_resolver, transport or UrllibTransport(30), base

    def _headers(self) -> dict[str, str]:
        tok = os.environ.get("GITHUB_TOKEN", "") or (self._resolver() if self._resolver else "")
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Brok"}
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    @property
    def authenticated(self) -> bool:
        return "Authorization" in self._headers()

    def _need_auth(self) -> None:
        if not self.authenticated:
            raise ToolError("GitHub token missing: set GITHUB_TOKEN (needs repo scope for write actions).")

    def get(self, path: str) -> Any:
        try:
            return self.t.get_json(self.base + path, self._headers())
        except ProviderError as exc:
            raise ToolError(str(exc))

    def post(self, path: str, body: dict) -> Any:
        self._need_auth()
        try:
            return self.t.post_json(self.base + path, self._headers(), body)
        except ProviderError as exc:
            raise ToolError(str(exc))


def register_github_tools(reg: ToolRegistry, gh: GitHubClient) -> None:
    S = {"type": "string"}
    obj = lambda props, req=None: {"type": "object", "properties": props, "required": req or list(props)}  # noqa: E731

    def repo(r: str) -> str:
        if r.count("/") == 1 and all(c.isalnum() or c in "-_./" for c in r) and ".." not in r:
            return r
        raise ToolError("repo must be owner/name")

    def issues(repository: str) -> str:
        return (
            "\n".join(
                f"#{i['number']} {i['title']}"
                for i in gh.get(f"/repos/{repo(repository)}/issues?state=open")
                if "pull_request" not in i
            )
            or "no open issues"
        )

    def prs(repository: str) -> str:
        return (
            "\n".join(f"#{p['number']} {p['title']}" for p in gh.get(f"/repos/{repo(repository)}/pulls?state=open"))
            or "no open PRs"
        )

    def commits(repository: str) -> str:
        return "\n".join(
            f"{c['sha'][:7]} {c['commit']['message'].splitlines()[0]}"
            for c in gh.get(f"/repos/{repo(repository)}/commits?per_page=10")
        )

    def branches(repository: str) -> str:
        return "\n".join(b["name"] for b in gh.get(f"/repos/{repo(repository)}/branches?per_page=100"))

    def browse(repository: str, path: str = "") -> str:
        data = gh.get(f"/repos/{repo(repository)}/contents/{path.lstrip('/')}")
        return (
            "\n".join(f"{d['type']} {d['path']}" for d in data)
            if isinstance(data, list)
            else f"file {data.get('path')} ({data.get('size')} bytes)"
        )

    def create_issue(repository: str, title: str, body: str = "") -> str:
        r = gh.post(f"/repos/{repo(repository)}/issues", {"title": title, "body": body})
        return f"created issue #{r['number']}: {r['html_url']}"

    def create_branch(repository: str, branch: str, from_sha: str) -> str:
        r = gh.post(f"/repos/{repo(repository)}/git/refs", {"ref": f"refs/heads/{branch}", "sha": from_sha})
        return f"created {r['ref']}"

    def create_pr(repository: str, title: str, head: str, base: str, body: str = "") -> str:
        r = gh.post(f"/repos/{repo(repository)}/pulls", {"title": title, "head": head, "base": base, "body": body})
        return f"created PR #{r['number']}: {r['html_url']}"

    L, N, H, REQ = Risk.LOW, Confirm.NEVER, Risk.HIGH, Confirm.REQUIRED
    for name, desc, props, req, risk, conf, fn in [
        ("github_issues", "List open issues.", {"repository": S}, None, L, N, issues),
        ("github_prs", "List open pull requests.", {"repository": S}, None, L, N, prs),
        ("github_commits", "Recent commits.", {"repository": S}, None, L, N, commits),
        ("github_branches", "List branches.", {"repository": S}, None, L, N, branches),
        ("github_browse", "Browse repo files.", {"repository": S, "path": S}, ["repository"], L, N, browse),
        (
            "github_create_issue",
            "Create an issue (remote change).",
            {"repository": S, "title": S, "body": S},
            ["repository", "title"],
            H,
            REQ,
            create_issue,
        ),
        (
            "github_create_branch",
            "Create a branch (remote change).",
            {"repository": S, "branch": S, "from_sha": S},
            None,
            H,
            REQ,
            create_branch,
        ),
        (
            "github_create_pr",
            "Open a pull request (remote change).",
            {"repository": S, "title": S, "head": S, "base": S, "body": S},
            ["repository", "title", "head", "base"],
            H,
            REQ,
            create_pr,
        ),
    ]:
        reg.register(ToolSpec(name, desc, obj(props, req), risk, conf, fn))
