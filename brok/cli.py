"""Terminal interface: ``brok-agent`` (coding agent, debugging, health, memory, privacy, doctor)."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .agent.debugger import debug_prompt
from .agent.health import analyze
from .agent.learning import STEPS, learning_prompt
from .agent.loop import AgentLoop, Limits
from .agent.tools import ApprovalRequest
from .ai.transport import ProviderError
from .commands import parse_command
from .config import BrokConfig
from .core import build_orchestrator, build_tools
from .logging_setup import setup_logging
from .memory import MemoryStore, SensitiveContentError
from .privacy import PrivacyTracker


def terminal_approver(req: ApprovalRequest) -> bool:
    print(f"\n⚠  Brok wants to run: {req.tool}  [risk: {req.risk.name}]\n   {req.summary}")
    if req.diff:
        print("--- proposed change (diff) ---\n" + req.diff[:4000])
    if not sys.stdin.isatty():
        print("   (non-interactive session: denied)")
        return False
    return input("   Apply? [y/N] ").strip().lower() in ("y", "yes", "ب", "بله")


def _run_agent(cfg: BrokConfig, task: str, project: str, mode: str, approver=terminal_approver) -> int:
    tracker = PrivacyTracker()
    orch = build_orchestrator(cfg, tracker)
    reg = build_tools(cfg, project, approver, tracker)
    mem = MemoryStore()
    task = (mem.context_for(project) and f"[Memory]\n{mem.context_for(project)}\n\n" or "") + task
    c = cfg.coding
    loop = AgentLoop(orch, reg, Limits(c.max_iterations, c.timeout_seconds, c.token_budget, c.tool_budget), mode,
                     on_event=lambda k, t: print(t, end="", flush=True) if k == "text" else print(f"\n🔧 {t}"))
    chain = orch.chain()
    prov = ("LOCAL AI" if chain[0].is_local else "CLOUD AI") if chain else "NO PROVIDER"
    print(f"[{prov}] working in {project} …")
    try:
        res = loop.run(task, language=cfg.ui.language)
    except ProviderError as exc:
        print(f"\nError: {exc}")
        return 2
    print(f"\n\n— {res.status} after {res.iterations} step(s), {res.tool_calls} tool call(s)")
    if res.error:
        print("Error:", res.error)
    return 0 if res.status == "done" else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="brok-agent", description="Brok coding agent (terminal)")
    ap.add_argument("--project", default=".", help="project root the agent may access")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ask", "code", "fix"):
        sp = sub.add_parser(name, help=f"{name}: natural language or /command text")
        sp.add_argument("text", nargs="+")
    d = sub.add_parser("debug", help="analyze an error/traceback (text or file)")
    d.add_argument("error", help="error text, or a file containing it")
    lp = sub.add_parser("learn", help="learning mode")
    lp.add_argument("step", choices=STEPS)
    lp.add_argument("topic", nargs="+")
    sub.add_parser("health", help="heuristic project health report")
    sub.add_parser("doctor", help="check providers/connection")
    sub.add_parser("privacy", help="what Brok stores/sends")
    m = sub.add_parser("memory", help="view/add/delete/clear memory")
    m.add_argument("action", choices=["list", "add", "delete", "clear"])
    m.add_argument("arg", nargs="*")
    a = ap.parse_args(argv)
    setup_logging("WARNING")
    cfg = BrokConfig.load()
    if a.cmd in ("ask", "code", "fix"):
        pc = parse_command(" ".join(a.text))
        mode = {"ask": pc.mode, "code": "CODING", "fix": "DEBUG"}[a.cmd]
        return _run_agent(cfg, pc.args if pc.name else pc.args, a.project, mode)
    if a.cmd == "debug":
        import os

        text = open(a.error, encoding="utf-8", errors="replace").read() if os.path.isfile(a.error) else a.error
        return _run_agent(cfg, debug_prompt(text, a.project, language=cfg.ui.language), a.project, "DEBUG")
    if a.cmd == "learn":
        return _run_agent(cfg, learning_prompt(a.step, " ".join(a.topic), cfg.ui.language), a.project, "LEARNING")
    if a.cmd == "health":
        rep = analyze(a.project)
        for f in rep.findings:
            print(f"[{f.severity:6}] {f.category:10} {f.where}: {f.message}")
        print(f"\n{len(rep.findings)} finding(s). {rep.disclaimer}")
        return 0
    if a.cmd == "doctor":
        orch = build_orchestrator(cfg)
        print(f"Primary: {cfg.ai.provider} · local_only={cfg.ai.local_only}")
        for name, p in orch.providers.items():
            try:
                print(f"  ✓ {p.badge:9} {p.test_connection()}")
            except ProviderError as exc:
                print(f"  ✗ {name}: {exc}")
        return 0
    if a.cmd == "privacy":
        mem = MemoryStore()
        print(f"Provider: {cfg.ai.provider} ({'local-only' if cfg.ai.local_only else 'cloud allowed'})")
        print(f"Memory: {mem.counts()}  ({mem.path})")
        print("Secrets: env vars / OS keyring only; never written to config, logs or memory.")
        print("Dangerous tools (delete, commit, push, risky commands) always ask first.")
        return 0
    mem = MemoryStore()
    if a.action == "list":
        for i in mem.list():
            print(f"{i.id}  [{i.kind}] {i.text}")
    elif a.action == "add":
        try:
            kind, *rest = a.arg
            print("saved", mem.add(kind, " ".join(rest)).id)
        except (ValueError, SensitiveContentError) as exc:
            print("Not saved:", exc)
            return 1
    elif a.action == "delete":
        print("deleted" if a.arg and mem.delete(a.arg[0]) else "not found")
    else:
        print("cleared", mem.clear(a.arg[0] if a.arg else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
