from __future__ import annotations

import datetime
import json
import os
from typing import Callable, Optional

EXAMPLE_PROMPT_TEXT = (
    "Use esm1b in Fastfold to run a fold job.\n\n"
    "Use these sequences:\n"
    "Sequence 1 (protein): "
    "MGLSDGEWQLVLNVWGKVEADIPGHGQEVLIRLFKGHPETLERFDKFKHLKSEDEMKASEDLKKHGATVLTALGGILKKKGHHEAEIKPLAQSHATKHKIPVKYLEFISECIIQVLQSKHPGDFGADAQRAMNKALELFRKDMASNYKELGFQG "
    "and show the prediction as cartoon colored by secondary structure."
)


class _MissingQtError(RuntimeError):
    pass


class _PromptCancelledError(RuntimeError):
    pass


def _qt():
    try:
        from pymol.Qt import QtCore, QtGui, QtWidgets
        return QtCore, QtGui, QtWidgets
    except Exception as e:
        raise _MissingQtError(
            "PyMOL Qt bindings are unavailable in this session."
        ) from e


class FastfoldAgentDialog:
    def __init__(self, run_prompt: Callable[..., None]):
        QtCore, QtGui, QtWidgets = _qt()
        from . import config, session, skills

        self._QtCore = QtCore
        self._QtGui = QtGui
        self._QtWidgets = QtWidgets
        self._config = config
        self._session = session
        self._skills = skills
        self._run_prompt = run_prompt
        self._is_running = False
        self._stream_started = False
        self._phase_text = "Idle"
        self._spinner_index = 0
        self._token_buffer: list[str] = []
        self._transcript_blocks: list[str] = []
        self._active_agent_markdown: Optional[str] = None
        self._worker = None
        self._worker_thread = None

        self.widget = QtWidgets.QDialog()
        self.widget.setWindowTitle("Fastfold Agent")
        self.widget.resize(900, 620)

        root = QtWidgets.QVBoxLayout(self.widget)

        model_row = QtWidgets.QHBoxLayout()
        model_row.addWidget(QtWidgets.QLabel("Model:"))

        self.model_combo = QtWidgets.QComboBox()
        model_options = list(self._config.SUPPORTED_ANTHROPIC_MODELS)
        current_model = str(
            self._config.get("anthropic_model") or self._config.DEFAULT_ANTHROPIC_MODEL
        ).strip()
        if current_model and current_model not in model_options:
            model_options.insert(0, current_model)
        self.model_combo.blockSignals(True)
        self.model_combo.addItems(model_options)
        if current_model:
            index = self.model_combo.findText(current_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo)

        model_row.addStretch(1)

        self.skills_btn = QtWidgets.QPushButton("Skills (0)")
        self.skills_btn.clicked.connect(self._on_show_skills)
        model_row.addWidget(self.skills_btn)

        self.export_combo = QtWidgets.QComboBox()
        self.export_combo.addItems(
            [
                "Export actions",
                "Export chat session (.json)",
                "Save session script (.py)",
                "Save last generated script (.py)",
            ]
        )
        self.export_combo.setCurrentIndex(0)
        self.export_combo.currentIndexChanged.connect(self._on_export_selected)
        model_row.addWidget(self.export_combo)

        root.addLayout(model_row)
        self._refresh_skills_indicator(force_reload=False)

        self.output = QtWidgets.QTextBrowser()
        self.output.setReadOnly(True)
        root.addWidget(self.output, stretch=2)

        self.input = QtWidgets.QPlainTextEdit()
        self.input.setPlaceholderText(
            "Type your message...\n"
            "Example:\n"
            "Run an OpenMMDL simulation with topology /path/protein.pdb and ligand /path/ligand.sdf"
        )
        self.input.setTabChangesFocus(False)
        root.addWidget(self.input, stretch=1)

        button_row = QtWidgets.QHBoxLayout()
        self.send_btn = QtWidgets.QPushButton("Send (Ctrl+Enter)")
        self.send_btn.clicked.connect(self._on_send)
        button_row.addWidget(self.send_btn)

        self.file_btn = QtWidgets.QPushButton("Insert File Path")
        self.file_btn.clicked.connect(self._insert_file_path)
        button_row.addWidget(self.file_btn)

        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.clicked.connect(self.output.clear)
        button_row.addWidget(self.clear_btn)

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        button_row.addWidget(self.cancel_btn)

        self.status = QtWidgets.QLabel("Idle")
        button_row.addWidget(self.status)

        button_row.addStretch(1)
        self.example_btn = QtWidgets.QPushButton("Example")
        self.example_btn.clicked.connect(self._insert_example_prompt)
        button_row.addWidget(self.example_btn)
        root.addLayout(button_row)

        shortcut_cls = getattr(QtWidgets, "QShortcut", None) or getattr(QtGui, "QShortcut", None)
        if shortcut_cls is None:
            raise _MissingQtError("Qt shortcut API is unavailable in this PyMOL build.")

        self._shortcut_send_ctrl_return = shortcut_cls(
            QtGui.QKeySequence("Ctrl+Return"), self.input
        )
        self._shortcut_send_ctrl_return.activated.connect(self._on_send)
        self._shortcut_send_ctrl_enter = shortcut_cls(
            QtGui.QKeySequence("Ctrl+Enter"), self.input
        )
        self._shortcut_send_ctrl_enter.activated.connect(self._on_send)

        self._token_flush_timer = QtCore.QTimer(self.widget)
        self._token_flush_timer.setInterval(40)
        self._token_flush_timer.timeout.connect(self._flush_token_buffer)

        self._status_timer = QtCore.QTimer(self.widget)
        self._status_timer.setInterval(250)
        self._status_timer.timeout.connect(self._update_running_status)

    def show(self) -> None:
        self._refresh_skills_indicator(force_reload=False)
        self.widget.show()
        self.widget.raise_()
        self.widget.activateWindow()

    def _append(self, text: str) -> None:
        note = text.strip()
        if not note:
            return
        self._push_markdown_block(self._note_block(note))
        self._render_transcript()

    def _push_markdown_block(self, block: str) -> None:
        self._transcript_blocks.append(block)
        # Bound transcript growth in long GUI sessions.
        if len(self._transcript_blocks) > 500:
            self._transcript_blocks = self._transcript_blocks[-500:]

    def _note_block(self, text: str) -> str:
        return f"```text\n{text}\n```"

    def _render_transcript(self) -> None:
        parts = list(self._transcript_blocks)
        if self._active_agent_markdown is not None:
            parts.append(f"**Agent:**\n\n{self._active_agent_markdown}")
        markdown = "\n\n".join(p for p in parts if p)
        if hasattr(self.output, "setMarkdown"):
            self.output.setMarkdown(markdown)
        else:
            self.output.setPlainText(markdown)
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _insert_file_path(self) -> None:
        _, _, QtWidgets = _qt()
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.widget,
            "Select input files",
            "",
            "All files (*)",
        )
        if not paths:
            return
        for p in paths:
            self.input.appendPlainText(f"\"{p}\"")

    def _insert_example_prompt(self) -> None:
        current = self.input.toPlainText().strip()
        if current:
            self.input.appendPlainText("")
        self.input.appendPlainText(EXAMPLE_PROMPT_TEXT)
        self.input.setFocus()

    def _on_model_changed(self, model: str) -> None:
        selected = (model or "").strip()
        if not selected:
            return
        if selected not in self._config.SUPPORTED_ANTHROPIC_MODELS:
            self._append(f"\n[Config] Ignored unsupported model: {selected}\n")
            return
        self._config.save_config("anthropic_model", selected)
        self._append(f"\n[Config] Anthropic model set to {selected}\n")

    def _refresh_skills_indicator(self, force_reload: bool = False) -> None:
        try:
            loaded = self._skills.list_skills(force_reload=force_reload)
            count = len(loaded)
        except Exception:
            self.skills_btn.setText("Skills (?)")
            self.skills_btn.setToolTip("Unable to read skills list.")
            return
        self.skills_btn.setText(f"Skills ({count})")
        self.skills_btn.setToolTip("Show loaded skills in chat")

    def _on_show_skills(self) -> None:
        try:
            loaded = self._skills.list_skills(force_reload=True)
        except Exception as e:
            self._append(f"\n[Skills] Failed to load skills: {e}\n")
            return

        self._refresh_skills_indicator(force_reload=False)
        if not loaded:
            self._append("\n[Skills] No skills loaded. Add SKILL.md folders under configured skills_paths.\n")
            return

        self._append(f"\n[Skills] Loaded {len(loaded)} skill(s):\n")
        for skill in loaded:
            desc = (skill.description or "").strip()
            line = f"  - {skill.name}"
            if desc:
                line += f": {desc}"
            self._append(line + "\n")

    def _default_export_dir(self) -> str:
        base = os.path.expanduser(self._config.get("output_dir") or os.getcwd())
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except OSError:
            fallback = os.path.expanduser("~/.fastfold-pymol-agent/scripts")
            os.makedirs(fallback, exist_ok=True)
            return fallback

    def _pick_save_path(self, title: str, filename: str, file_filter: str) -> str:
        _, _, QtWidgets = _qt()
        start = os.path.join(self._default_export_dir(), filename)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.widget, title, start, file_filter)
        return path or ""

    def _session_log(self):
        sess = self._session.get_session()
        return sess, sess.get_log()

    def _on_export_session_json(self) -> None:
        sess, log = self._session_log()
        if not log:
            self._append("\n[Export] No exchanges in this session yet.\n")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._pick_save_path(
            "Export chat session as JSON",
            f"fastfold_pymol_agent_session_{ts}.json",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        payload = {
            "started_at": sess.started_at,
            "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exchanges": log,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self._append(f"\n[Export] Session JSON saved to: {path}\n")
        except OSError as e:
            self._append(f"\n[Export] Failed to save JSON: {e}\n")

    def _on_export_selected(self, index: int) -> None:
        if index <= 0:
            return
        try:
            if index == 1:
                self._on_export_session_json()
            elif index == 2:
                self._on_save_session_script()
            elif index == 3:
                self._on_save_last_generated_script()
        finally:
            self.export_combo.blockSignals(True)
            self.export_combo.setCurrentIndex(0)
            self.export_combo.blockSignals(False)

    def _render_session_script(self, started_at: str, log: list[dict]) -> str:
        lines = [
            "# Fastfold PyMOL Agent session log",
            f"# Session started: {started_at}",
            f"# Saved:           {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "from pymol import cmd",
            "",
        ]
        for i, entry in enumerate(log, 1):
            lines.append(f"# -- Step {i}: {entry.get('timestamp', '')}")
            lines.append(f"# Prompt: {entry.get('prompt', '')}")
            summary = entry.get("summary") or ""
            if summary:
                lines.append(f"# {summary}")
            code = entry.get("code")
            lines.append(code if code else "# (no commands generated)")
            lines.append("")
        return "\n".join(lines)

    def _on_save_session_script(self) -> None:
        sess, log = self._session_log()
        if not log:
            self._append("\n[Export] No exchanges in this session yet.\n")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._pick_save_path(
            "Save session as runnable script",
            f"fastfold_pymol_agent_session_{ts}.py",
            "Python files (*.py);;All files (*)",
        )
        if not path:
            return

        content = self._render_session_script(sess.started_at, log)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._append(f"\n[Export] Session script saved to: {path}\n")
        except OSError as e:
            self._append(f"\n[Export] Failed to save session script: {e}\n")

    def _on_save_last_generated_script(self) -> None:
        _, log = self._session_log()
        code = ""
        for entry in reversed(log):
            maybe_code = entry.get("code")
            if maybe_code:
                code = maybe_code
                break
        if not code:
            self._append("\n[Export] No generated script found in this session yet.\n")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._pick_save_path(
            "Save last generated script",
            f"fastfold_pymol_agent_{ts}.py",
            "Python files (*.py);;All files (*)",
        )
        if not path:
            return

        header = (
            "# Generated by Fastfold PyMOL Agent\n"
            f"# {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "from pymol import cmd\n\n"
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + code + "\n")
            self._append(f"\n[Export] Last generated script saved to: {path}\n")
        except OSError as e:
            self._append(f"\n[Export] Failed to save generated script: {e}\n")

    def _set_running(self, running: bool) -> None:
        self._is_running = running
        self.send_btn.setEnabled(not running)
        self.file_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.model_combo.setEnabled(not running)
        self.skills_btn.setEnabled(not running)
        self.export_combo.setEnabled(not running)
        self.example_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        if running:
            self._spinner_index = 0
            self._status_timer.start()
            self._token_flush_timer.start()
            self._update_running_status()
        else:
            self._status_timer.stop()
            self._token_flush_timer.stop()
            self._phase_text = "Idle"
            self.status.setText("Idle")

    def _set_phase(self, text: str) -> None:
        self._phase_text = text
        self._update_running_status()

    def _update_running_status(self) -> None:
        if not self._is_running:
            self.status.setText("Idle")
            return
        spinner = ("|", "/", "-", "\\")
        icon = spinner[self._spinner_index % len(spinner)]
        self._spinner_index += 1
        self.status.setText(f"{self._phase_text} {icon}")

    def _on_worker_token(self, token: str) -> None:
        if not self._stream_started:
            self._stream_started = True
            self._active_agent_markdown = ""
            self._set_phase("Streaming")
        self._token_buffer.append(token)

    def _flush_token_buffer(self) -> None:
        if not self._token_buffer:
            return
        chunk = "".join(self._token_buffer)
        self._token_buffer.clear()
        if self._active_agent_markdown is None:
            self._active_agent_markdown = ""
        self._active_agent_markdown += chunk
        self._render_transcript()

    def _on_send(self) -> None:
        if self._is_running:
            return
        prompt = self.input.toPlainText().strip()
        if not prompt:
            return
        self.input.clear()
        self._push_markdown_block(f"**You:** {prompt}")
        self._render_transcript()
        self._stream_started = False
        self._active_agent_markdown = None
        self._token_buffer.clear()
        self._set_phase("Thinking")
        self._set_running(True)
        self._start_worker(prompt)

    def _start_worker(self, prompt: str) -> None:
        QtCore, _, _ = _qt()
        worker = _PromptWorker(self._run_prompt, prompt)
        thread = QtCore.QThread(self.widget)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.token.connect(self._on_worker_token)
        worker.phase.connect(self._set_phase)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

        self._worker = worker
        self._worker_thread = thread

    def _on_worker_error(self, message: str) -> None:
        self._append(f"\n[GUI Error] {message}\n")

    def _on_worker_finished(self, cancelled: bool) -> None:
        self._flush_token_buffer()
        if cancelled:
            self._active_agent_markdown = None
            self._append("[Cancelled]")
        elif self._stream_started and self._active_agent_markdown is not None:
            self._push_markdown_block(f"**Agent:**\n\n{self._active_agent_markdown}")
            self._active_agent_markdown = None
            self._render_transcript()
        self._set_running(False)
        self._worker = None
        self._worker_thread = None

    def _on_cancel(self) -> None:
        if not self._worker:
            return
        self._set_phase("Cancelling")
        self.cancel_btn.setEnabled(False)
        self._worker.request_cancel()


class _PromptWorker:
    def __init__(self, run_prompt: Callable[..., None], prompt: str):
        QtCore, _, _ = _qt()
        self._run_prompt = run_prompt
        self._prompt = prompt
        self._cancel_requested = False
        self._cancelled = False

        class _WorkerObject(QtCore.QObject):
            token = QtCore.Signal(str)
            phase = QtCore.Signal(str)
            error = QtCore.Signal(str)
            finished = QtCore.Signal(bool)

            def __init__(self, parent):
                super().__init__()
                self._parent = parent

            def run(self):
                self._parent._run_internal()

        self._obj = _WorkerObject(self)
        self.token = self._obj.token
        self.phase = self._obj.phase
        self.error = self._obj.error
        self.finished = self._obj.finished

    def moveToThread(self, thread) -> None:
        self._obj.moveToThread(thread)

    def deleteLater(self) -> None:
        self._obj.deleteLater()

    @property
    def run(self):
        return self._obj.run

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _on_token(self, token: str) -> None:
        if self._cancel_requested:
            self._cancelled = True
            raise _PromptCancelledError("Cancelled by user")
        self.token.emit(token)

    def _run_internal(self) -> None:
        self.phase.emit("Thinking")
        try:
            self._run_prompt(self._prompt, on_token=self._on_token)
        except _PromptCancelledError:
            pass
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit(self._cancelled)


_DIALOG: Optional[FastfoldAgentDialog] = None


def show_dialog(run_prompt: Callable[..., None]) -> None:
    global _DIALOG
    if _DIALOG is None:
        _DIALOG = FastfoldAgentDialog(run_prompt=run_prompt)
    _DIALOG.show()
