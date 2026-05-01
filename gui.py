from __future__ import annotations

from typing import Callable, Optional


class _MissingQtError(RuntimeError):
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
        self.status.setText("Running..." if running else "Idle")

    def _on_token(self, token: str) -> None:
        if not self._stream_started:
            self._append("Agent: ")
            self._stream_started = True
        self._append(token)
        self._QtWidgets.QApplication.processEvents()

    def _on_send(self) -> None:
        if self._is_running:
            return
        prompt = self.input.toPlainText().strip()
        if not prompt:
            return
        self.input.clear()
        self._append(f"\n\nYou: {prompt}\n")
        self._stream_started = False
        self._set_running(True)
        try:
            self._run_prompt(prompt, on_token=self._on_token)
        except Exception as e:
            self._append(f"\n[GUI Error] {e}\n")
        finally:
            if self._stream_started:
                self._append("\n")
            self._set_running(False)


_DIALOG: Optional[FastFoldAgentDialog] = None


def show_dialog(run_prompt: Callable[..., None]) -> None:
    global _DIALOG
    if _DIALOG is None:
        _DIALOG = FastFoldAgentDialog(run_prompt=run_prompt)
    _DIALOG.show()
