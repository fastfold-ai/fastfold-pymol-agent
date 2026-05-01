"""Shared utility functions used by both __init__.py and gui.py."""

import os
import re
from typing import Optional, Tuple

# Calls that must never run inside generated code — they close PyMOL
BLOCKED_CALLS = ("cmd.quit", "cmd.exit", "pymol.quit", "sys.exit", "quit(", "exit(")


def execute_code(code: str, output_dir: str = "") -> Optional[str]:
    """Execute a Python code block in the PyMOL context.

    Returns an error string on failure, or None on success.
    Imports are lazy so this module stays importable without PyMOL.
    """
    for blocked in BLOCKED_CALLS:
        if blocked in code:
            return f"Blocked unsafe call: '{blocked}'"

    import math
    import csv
    from pymol import cmd
    from pymol import stored as _pymol_stored

    effective_outdir = output_dir or os.getcwd()
    skills_root = os.path.expanduser("~/.fastfold-pymol-agent/skills")
    fastfold_api_key = (os.environ.get("FASTFOLD_API_KEY") or "").strip()
    ns = {
        "cmd": cmd,
        "output_dir": effective_outdir,
        "skills_root": skills_root,
        "fastfold_api_key": fastfold_api_key,
        "os": os,
        "math": math,
        "csv": csv,
        "stored": _pymol_stored,
    }
    try:
        exec(compile(code, "<fastfold_pymol_agent>", "exec"), ns)
        return None
    except Exception as e:
        return str(e)


def _looks_like_python_code(block: str) -> bool:
    """Heuristic guard so plain fenced text isn't executed as Python."""
    text = (block or "").strip()
    if not text:
        return False
    hints = (
        "cmd.",
        "stored.",
        "import ",
        "from ",
        "def ",
        "for ",
        "while ",
        "if ",
        "with ",
        "=",
        "print(",
    )
    return any(h in text for h in hints)


def parse_response(response: str) -> Tuple[str, str]:
    """Return (summary_text, code_block_text). Either may be empty string.

    Only explicit python/pymol fenced blocks are trusted by default.
    Unlabeled fenced blocks are treated as code only if they clearly look like Python.
    """
    pattern = r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```"
    matches = list(re.finditer(pattern, response, re.DOTALL))
    if not matches:
        return response.strip(), ""

    for match in matches:
        lang = (match.group("lang") or "").strip().lower()
        body = (match.group("body") or "").strip()
        if lang in ("python", "py", "pymol"):
            summary = response[: match.start()].strip().rstrip(":").strip()
            return summary, body
        if not lang and _looks_like_python_code(body):
            summary = response[: match.start()].strip().rstrip(":").strip()
            return summary, body

    # No trustworthy code block found: treat as plain text response.
    return response.strip(), ""
