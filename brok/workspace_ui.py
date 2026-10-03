"""Coding workspace: file explorer, editor, AI chat, diff viewer, output/terminal, problems, git, project info."""

from __future__ import annotations

import base64
import html
import os
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import i18n
from .agent.builtin_tools import build_registry  # noqa: F401  (re-exported for tests)
from .agent.debugger import debug_prompt
from .agent.health import analyze
from .agent.learning import STEPS, learning_prompt
from .agent.loop import AgentLoop, Limits
from .agent.project import detect_project
from .agent.tools import ApprovalRequest, ToolRegistry
from .ai.messages import ImageInput
from .ai.orchestrator import AIOrchestrator, infer_mode
from .avatar.engine import AvatarEngine
from .avatar.manager import AvatarManager
from .commands import parse_command

tr = i18n.tr

#: Quick actions on the selected code (instruction is Persian-first, like the product).
QUICK_ACTIONS = (
    ("Explain", "این کد را توضیح بده", "CODING"),
    ("Find bug", "این باگ را پیدا کن و اصلاحش کن", "DEBUG"),
    ("Optimize", "بهینه‌اش کن", "CODING"),
    ("Write tests", "برای این تست بنویس", "CODING"),
    ("To Flutter", "این را به Flutter تبدیل کن", "CODING"),
)


class _ApprovalHolder:
    def __init__(self, req: ApprovalRequest) -> None:
        self.req, self.result, self.event = req, False, threading.Event()


class ApprovalDialog(QtWidgets.QDialog):
    """Shows what Brok wants to do (with BEFORE/AFTER diff) and asks Apply / Reject."""

    def __init__(self, req: ApprovalRequest, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Approval required"))
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"<b>{req.tool}</b> — " + tr("Risk: {risk}").format(risk=req.risk.name)))
        lay.addWidget(QtWidgets.QLabel(req.summary))
        if req.diff:
            box = QtWidgets.QPlainTextEdit(req.diff)
            box.setReadOnly(True)
            box.setMinimumSize(560, 260)
            lay.addWidget(box)
        btns = QtWidgets.QDialogButtonBox()
        apply_b = btns.addButton(tr("Apply"), QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        reject_b = btns.addButton(tr("Reject"), QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        reject_b.setDefault(True)  # the safe choice is the default
        apply_b.clicked.connect(self.accept)
        reject_b.clicked.connect(self.reject)
        lay.addWidget(btns)


class AgentWorker(QtCore.QThread):
    text = QtCore.Signal(str)
    tool = QtCore.Signal(str)
    approval = QtCore.Signal(object)
    done = QtCore.Signal(str, str)  # status, error

    def __init__(self, loop: AgentLoop, task: str, language: str, images: list[ImageInput] | None = None) -> None:
        super().__init__()
        self.loop, self.task, self.language, self.images = loop, task, language, images or []

    def run(self) -> None:
        self.loop.on_event = lambda k, t: (self.text if k == "text" else self.tool).emit(t)
        try:
            res = self.loop.run(self.task, language=self.language, images=self.images)
            self.done.emit(res.status, res.error)
        except Exception as exc:  # noqa: BLE001 - never let a worker crash the app
            self.done.emit("error", str(exc))


class WorkspaceWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        project: str,
        orchestrator: AIOrchestrator,
        registry_factory: Callable[[str, Callable[[ApprovalRequest], bool]], ToolRegistry],
        limits: Limits | None = None,
        language: str = "fa",
        parent: QtWidgets.QWidget | None = None,
        avatar: AvatarManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.orch, self.registry_factory = orchestrator, registry_factory
        self.limits, self.language = limits or Limits(), language
        self.avatar = avatar or AvatarManager(AvatarEngine())
        self.project = ""
        self.current_file: Path | None = None
        self.worker: AgentWorker | None = None
        self.setWindowTitle(tr("Coding Workspace"))
        self.resize(1280, 800)
        self._build_ui()
        self.open_project(project)

    # ---------------- UI ----------------
    def _dock(self, title: str, widget: QtWidgets.QWidget, area: QtCore.Qt.DockWidgetArea) -> QtWidgets.QDockWidget:
        d = QtWidgets.QDockWidget(tr(title), self)
        d.setWidget(widget)
        d.setObjectName(title)
        self.addDockWidget(area, d)
        return d

    def _build_ui(self) -> None:
        L, R, B = (
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea,
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            QtCore.Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self.model = QtWidgets.QFileSystemModel(self)
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.model)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.doubleClicked.connect(lambda i: self.open_file(self.model.filePath(i)))
        self._dock("Files", self.tree, L)

        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setLayoutDirection(
            QtCore.Qt.LayoutDirection.LeftToRight
        )  # code is always LTR, even in a Persian UI
        self.file_label = QtWidgets.QLabel("—")
        center = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(center)
        cl.addWidget(self.file_label)
        cl.addWidget(self.editor)
        bar = QtWidgets.QHBoxLayout()
        self.quick_buttons = {}
        for key, instruction, mode in QUICK_ACTIONS:
            b = QtWidgets.QPushButton(tr(key))
            b.clicked.connect(lambda _=False, i=instruction, m=mode: self.ask_about_selection(i, m))
            bar.addWidget(b)
            self.quick_buttons[key] = b
        self.save_btn = QtWidgets.QPushButton(tr("Save"))
        self.save_btn.clicked.connect(self.save_file)
        bar.addStretch(1)
        bar.addWidget(self.save_btn)
        cl.addLayout(bar)
        self.setCentralWidget(center)

        chat = QtWidgets.QWidget()
        chl = QtWidgets.QVBoxLayout(chat)
        self.badge = QtWidgets.QLabel()
        self.transcript = QtWidgets.QTextBrowser()
        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText(tr("Ask Brok about the project or selected code…"))
        self.input.returnPressed.connect(self.send)
        row = QtWidgets.QHBoxLayout()
        self.send_btn = QtWidgets.QPushButton(tr("Send"))
        self.send_btn.clicked.connect(self.send)
        self.stop_btn = QtWidgets.QPushButton(tr("Stop"))
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        self.attach_btn = QtWidgets.QPushButton(tr("Attach image…"))
        self.attach_btn.clicked.connect(self.attach_image_dialog)
        self.shot_btn = QtWidgets.QPushButton(tr("Screenshot"))
        self.shot_btn.clicked.connect(self.attach_screenshot)
        self.images_label = QtWidgets.QLabel("")
        self.pending_images: list[ImageInput] = []
        row.addWidget(self.send_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.attach_btn)
        row.addWidget(self.shot_btn)
        for w in (self.badge, self.transcript, self.images_label, self.input):
            chl.addWidget(w)
        chl.addLayout(row)
        self._dock("Chat", chat, R)

        self.diff_view = QtWidgets.QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.cmd_input = QtWidgets.QLineEdit()
        self.cmd_input.setPlaceholderText(tr("Run command"))
        self.cmd_input.returnPressed.connect(self.run_terminal_command)
        term = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(term)
        tl.addWidget(self.output)
        tl.addWidget(self.cmd_input)
        self.problems = QtWidgets.QListWidget()
        self.git_view = QtWidgets.QPlainTextEdit()
        self.git_view.setReadOnly(True)
        self.info_view = QtWidgets.QPlainTextEdit()
        self.info_view.setReadOnly(True)
        tabs = QtWidgets.QTabWidget()
        tab_pages: tuple[tuple[str, QtWidgets.QWidget], ...] = (
            ("Diff", self.diff_view),
            ("Output", term),
            ("Problems", self.problems),
            ("Git", self.git_view),
            ("Project", self.info_view),
            ("Assistants", self._build_assistants()),
        )
        for name, page in tab_pages:
            tabs.addTab(page, tr(name))
        self.tabs = tabs
        self._dock("Output", tabs, B)
        refresh = self.menuBar().addAction(tr("Refresh"))
        refresh.triggered.connect(self.refresh_panels)
        self._refresh_badge()

    # ---------------- project / files ----------------
    def open_project(self, path: str) -> None:
        path = os.path.realpath(path)
        self.project = path
        self.model.setRootPath(path)
        self.tree.setRootIndex(self.model.index(path))
        self.registry = self.registry_factory(path, self.ask_from_worker)
        self.refresh_panels()
        self.setWindowTitle(f"{tr('Coding Workspace')} — {os.path.basename(path)}")

    def refresh_panels(self) -> None:
        info = detect_project(self.project)
        self.info_view.setPlainText(
            f"Languages: {', '.join(info.languages) or '—'}\nFrameworks: {', '.join(info.frameworks) or '—'}\n"
            f"Package managers: {', '.join(info.package_managers) or '—'}\n"
            f"Entry points: {', '.join(info.entry_points) or '—'}\n"
            f"Tests: {info.test_command or '—'}\nLint: {info.lint_command or '—'}\nBuild: {info.build_system or '—'}\n"
            f"Git: {'yes' if info.git_repo else 'no'}"
        )
        self.git_view.setPlainText(self.registry.execute("git_status", {}) if info.git_repo else "—")
        self.problems.clear()
        rep = analyze(self.project)
        for f in rep.findings[:300]:
            self.problems.addItem(f"[{f.severity}] {f.category} {f.where}: {f.message}")
        self.problems.addItem(rep.disclaimer)

    def open_file(self, path: str) -> bool:
        p = Path(path)
        if not p.is_file():
            return False
        try:
            if p.stat().st_size > 2_000_000:
                self.output.appendPlainText(f"{p.name}: too large to open")
                return False
            self.editor.setPlainText(p.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            self.output.appendPlainText(f"{p.name}: {exc}")
            return False
        self.current_file = p
        self.file_label.setText(os.path.relpath(p, self.project))
        return True

    def save_file(self) -> bool:
        if not self.current_file:
            return False
        try:
            self.current_file.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self.output.appendPlainText(f"save failed: {exc}")
            return False
        self.output.appendPlainText(tr("Saved {name}").format(name=self.current_file.name))
        return True

    # ---------------- agent ----------------
    def _refresh_badge(self) -> None:
        chain = self.orch.chain()
        if not chain:
            self.badge.setText("⚠ " + tr("No AI provider available (local-only mode or no provider configured)"))
        else:
            p = chain[0]
            self.badge.setText(f"{'🟢 ' + tr('LOCAL AI') if p.is_local else '☁ ' + tr('CLOUD AI')} · {p.name}")

    def ask_about_selection(self, instruction: str, mode: str) -> None:
        sel = self.editor.textCursor().selectedText().replace("\u2029", "\n")
        rel = os.path.relpath(self.current_file, self.project) if self.current_file else "(no file)"
        body = sel or self.editor.toPlainText()[:6000]
        self.start_task(f"{instruction}\n\nFile: {rel}\n```\n{body}\n```", mode)

    def send(self) -> None:
        text = self.input.text().strip()
        if not text or self.worker is not None:
            return
        self.input.clear()
        pc = parse_command(text)
        self.start_task(pc.args if pc and pc.name else text, pc.mode if pc else infer_mode(text))

    def start_task(self, task: str, mode: str) -> None:
        if self.worker is not None:
            return
        self._refresh_badge()
        self.transcript.append(f"<p><b>{tr('Request')}:</b> {html.escape(task[:400])}</p>")
        self.avatar.on_event("ai_thinking")
        loop = AgentLoop(self.orch, self.registry, self.limits, mode)
        images, self.pending_images = self.pending_images, []
        self._update_images_label()
        self.worker = AgentWorker(loop, task, self.language, images)
        self.worker.text.connect(self._on_text)
        self.worker.tool.connect(self._on_tool)
        self.worker.approval.connect(self._on_approval)
        self.worker.done.connect(self._on_done)
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    # ---------------- vision ----------------
    def _update_images_label(self) -> None:
        n = len(self.pending_images)
        self.images_label.setText(tr("{n} image(s) attached").format(n=n) if n else "")

    def add_image_bytes(self, data: bytes, media_type: str) -> None:
        self.pending_images.append(ImageInput(base64.b64encode(data).decode("ascii"), media_type))
        self._update_images_label()

    def attach_image_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, tr("Attach image…"), self.project, "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if path:
            self.attach_image_file(path)

    def attach_image_file(self, path: str) -> bool:
        media = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext not in media or os.path.getsize(path) > 8_000_000:
                self.output.appendPlainText(tr("Unsupported or too large image"))
                return False
            with open(path, "rb") as fh:
                self.add_image_bytes(fh.read(), media[ext])
        except OSError as exc:
            self.output.appendPlainText(str(exc))
            return False
        return True

    def attach_screenshot(self) -> bool:
        """Grab the primary screen (downscaled to ≤1600px) and attach it to the next message."""
        screen = QtGui.QGuiApplication.primaryScreen()
        pix = screen.grabWindow(0) if screen else QtGui.QPixmap()
        if pix.isNull():
            self.output.appendPlainText(tr("Screenshot is not available on this system"))
            return False
        if pix.width() > 1600:
            pix = pix.scaledToWidth(1600, QtCore.Qt.TransformationMode.SmoothTransformation)
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buf, "PNG")
        self.add_image_bytes(bytes(buf.data().data()), "image/png")
        return True

    # ---------------- assistants: debugger / learning / health ----------------
    def _build_assistants(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel("<b>" + tr("AI Debugger") + "</b>"))
        self.debug_input = QtWidgets.QPlainTextEdit()
        self.debug_input.setPlaceholderText(tr("Paste an error / stack trace…"))
        self.debug_input.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        self.debug_btn = QtWidgets.QPushButton(tr("Analyze and fix"))
        self.debug_btn.clicked.connect(self.run_debugger)
        lay.addWidget(self.debug_input)
        lay.addWidget(self.debug_btn)
        lay.addWidget(QtWidgets.QLabel("<b>" + tr("Learning mode") + "</b>"))
        row = QtWidgets.QHBoxLayout()
        self.learn_topic = QtWidgets.QLineEdit()
        self.learn_topic.setPlaceholderText(tr("Topic, e.g. for loop"))
        self.learn_step = QtWidgets.QComboBox()
        for s in STEPS:
            self.learn_step.addItem(tr(s.capitalize()), s)
        self.learn_btn = QtWidgets.QPushButton(tr("Teach me"))
        self.learn_btn.clicked.connect(self.run_learning)
        for x in (self.learn_topic, self.learn_step, self.learn_btn):
            row.addWidget(x)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel("<b>" + tr("Project health") + "</b>"))
        self.health_btn = QtWidgets.QPushButton(tr("Run health report"))
        self.health_btn.clicked.connect(self.run_health)
        self.health_label = QtWidgets.QLabel("")
        lay.addWidget(self.health_btn)
        lay.addWidget(self.health_label)
        lay.addStretch(1)
        return w

    def run_debugger(self) -> None:
        text = self.debug_input.toPlainText().strip()
        if text:
            self.start_task(debug_prompt(text, self.project, language=self.language), "DEBUG")

    def run_learning(self) -> None:
        topic = self.learn_topic.text().strip()
        if topic:
            self.start_task(learning_prompt(self.learn_step.currentData(), topic, self.language), "LEARNING")

    def run_health(self) -> None:
        self.refresh_panels()
        rep = analyze(self.project)
        counts: dict[str, int] = {}
        for f in rep.findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        self.health_label.setText(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or tr("No findings"))
        self.tabs.setCurrentWidget(self.problems)

    def stop(self) -> None:
        if self.worker:
            self.worker.loop.cancel()

    def _on_text(self, t: str) -> None:
        self.avatar.on_event("speaking")
        self.transcript.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.transcript.insertPlainText(t)

    def _on_tool(self, t: str) -> None:
        self.avatar.on_agent_event("tool", t)
        self.output.appendPlainText("🔧 " + t[:300])

    def _on_done(self, status: str, error: str) -> None:
        self.transcript.append(f"<p><i>— {status}{(': ' + error) if error else ''}</i></p>")
        self.avatar.on_event("error" if status == "error" else "success" if status == "done" else "idle")
        if self.worker:
            self.worker.wait()
        self.worker = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.current_file and self.current_file.is_file():
            self.open_file(str(self.current_file))  # show what the agent changed
        self.refresh_panels()

    # approval: tool runs in the worker thread; the dialog must run in the GUI thread
    def ask_from_worker(self, req: ApprovalRequest) -> bool:
        holder = _ApprovalHolder(req)
        if self.worker is None:
            return False
        self.worker.approval.emit(holder)
        while not holder.event.wait(0.1):
            if self.worker is not None and self.worker.loop._cancel.is_set():
                return False
        return holder.result

    def _show_approval(self, req: ApprovalRequest) -> bool:
        return ApprovalDialog(req, self).exec() == QtWidgets.QDialog.DialogCode.Accepted

    def _on_approval(self, holder: _ApprovalHolder) -> None:
        if holder.req.diff:
            self.diff_view.setPlainText(holder.req.diff)
            self.tabs.setCurrentWidget(self.diff_view)
        self.avatar.on_event("confused")
        holder.result = bool(self._show_approval(holder.req))
        holder.event.set()

    def run_terminal_command(self) -> None:
        cmd = self.cmd_input.text().strip()
        if cmd:
            self.cmd_input.clear()
            self.output.appendPlainText(f"$ {cmd}")
            # same sandbox + approval path as the agent: risky commands ask, dangerous ones are blocked
            self.output.appendPlainText(self.registry.execute("run_command", {"command": cmd}))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self.worker:
            self.worker.loop.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


def open_workspace(parent: QtWidgets.QWidget | None = None, project: str = "") -> WorkspaceWindow | None:
    """Entry point used by the tray/context menu."""
    from .config import BrokConfig
    from .core import build_orchestrator, build_tools
    from .privacy import PrivacyTracker

    cfg = BrokConfig.load()
    if not project:
        project = QtWidgets.QFileDialog.getExistingDirectory(parent, tr("Select a project folder"), str(Path.home()))
        if not project:
            return None
    tracker = PrivacyTracker()
    orch = build_orchestrator(cfg, tracker)
    c = cfg.coding
    win = WorkspaceWindow(
        project,
        orch,
        lambda root, appr: build_tools(cfg, root, appr, tracker),
        Limits(c.max_iterations, c.timeout_seconds, c.token_budget, c.tool_budget),
        cfg.ui.language,
    )
    win.show()
    return win
