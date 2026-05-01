from __future__ import annotations

from typing import Callable, Optional


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


class FastFoldAgentDialog:
    def __init__(self, run_prompt: Callable[..., None]):
        QtCore, QtGui, QtWidgets = _qt()
        self._QtCore = QtCore
        self._QtGui = QtGui
        self._QtWidgets = QtWidgets
        self._run_prompt = run_prompt
        self._is_running = False
        self._stream_started = False
        self._phase_text = "Idle"
        self._spinner_index = 0
        self._token_buffer: list[str] = []
        self._worker = None
        self._worker_thread = None

        self.widget = QtWidgets.QDialog()
        self.widget.setWindowTitle("FastFold Agent")
        self.widget.resize(900, 620)

        root = QtWidgets.QVBoxLayout(self.widget)

        help_label = QtWidgets.QLabel(
            "Use multiline prompts and send with Ctrl+Enter. "
            "This input avoids PyMOL parser SyntaxErrors from bare text."
        )
        help_label.setWordWrap(True)
        root.addWidget(help_label)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        # Keep the UI responsive in long sessions by trimming old output blocks.
        self.output.document().setMaximumBlockCount(4000)
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
        self.widget.show()
        self.widget.raise_()
        self.widget.activateWindow()

    def _append(self, text: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

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

    def _set_running(self, running: bool) -> None:
        self._is_running = running
        self.send_btn.setEnabled(not running)
        self.file_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
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
            self._append("Agent: ")
            self._stream_started = True
            self._set_phase("Streaming")
        self._token_buffer.append(token)

    def _flush_token_buffer(self) -> None:
        if not self._token_buffer:
            return
        chunk = "".join(self._token_buffer)
        self._token_buffer.clear()
        self._append(chunk)

    def _on_send(self) -> None:
        if self._is_running:
            return
        prompt = self.input.toPlainText().strip()
        if not prompt:
            return
        self.input.clear()
        self._append(f"\n\nYou: {prompt}\n")
        self._stream_started = False
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
            self._append("\n[Cancelled]\n")
        elif self._stream_started:
            self._append("\n")
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


_DIALOG: Optional[FastFoldAgentDialog] = None


def show_dialog(run_prompt: Callable[..., None]) -> None:
    global _DIALOG
    if _DIALOG is None:
        _DIALOG = FastFoldAgentDialog(run_prompt=run_prompt)
    _DIALOG.show()
