"""
FastFold PyMOL Agent — natural-language control for PyMOL.

Commands registered in the PyMOL command line:
  fastfold <prompt>
  agent <prompt>                         conversational alias for follow-up turns
  fastfold ui                            open multiline FastFold Agent window
  fastfold dry <prompt>
  fastfold save [filename.py] <prompt>
  fastfold save [filename.py]            save last generated script
  fastfold undo
  fastfold reset
  fastfold setup                          guided setup (non-blocking in PyMOL)
  fastfold setup <anthropic_key> <fastfold_key>
  fastfold setup anthropic <api_key>
  fastfold setup fastfold <api_key>
  fastfold doctor
  fastfold agent on|off|status
  fastfold config show|set <key> <value>
  fastfold skills list|show|howto|reload|search
  fastfold log show|save|export [filename]
  fastfold help

Short alias:
  ff ... (same subcommands as fastfold)
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import shlex
import re
from typing import Optional

# ── Module-level state ────────────────────────────────────────────────────────
_LAST_SCRIPT: Optional[str] = None
_UNDO_STATE: Optional[dict] = None
_LAST_EXECUTION_NOTE: str = ""
_WORKFLOW_KEYWORDS = (
    "fastfold",
    "fold job",
    "esm",
    "esm1b",
    "openfold",
    "chai",
    "intellifold",
    "boltz",
    "webhook",
    "openmm",
    "openmmdl",
)


# ── Plugin registration ───────────────────────────────────────────────────────
def __init_plugin__(app=None):
    from pymol import cmd
    from . import config

    cmd.extend("fastfold", _fastfold)
    cmd.extend("ff", _fastfold)
    cmd.extend("agent", _agent_command)
    try:
        from pymol.plugins import addmenuitemqt

        addmenuitemqt("FastFold Agent", _fastfold_ui)
    except Exception:
        # PyMOL builds without Qt plugin menus should still load commands.
        pass

    if not os.path.exists(config.CONFIG_PATH):
        _print_setup_wizard(first_run=True)
    else:
        cfg = config.load_config()
        print("FastFold PyMOL Agent loaded. Type 'fastfold help' for usage.")
        print("Type 'fastfold skills list' to inspect installed skills.\n")
        if cfg.get("agent_mode", False):
            print("Agent mode is ON. Use `agent <message>` for follow-up turns.\n")
        else:
            print("Tip: every natural-language follow-up must start with `ff`, `fastfold`, or `agent`.\n")
        print("Tip: run `fastfold ui` for a multiline input window.\n")


# ── Root command router ───────────────────────────────────────────────────────
def _tokenize(raw: str) -> list[str]:
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def _fastfold(*args, **kwargs):
    raw = " ".join(str(a) for a in args).strip()
    if not raw:
        _print_help()
        return

    tokens = _tokenize(raw)
    if not tokens:
        _print_help()
        return

    verb = tokens[0].lower()
    rest = tokens[1:]

    if verb in ("help", "-h", "--help"):
        _print_help()
        return
    if verb == "setup":
        _fastfold_setup(rest)
        return
    if verb == "ui":
        _fastfold_ui()
        return
    if verb == "doctor":
        _fastfold_doctor()
        return
    if verb == "agent":
        _fastfold_agent(rest)
        return
    if verb == "config":
        _fastfold_config(rest)
        return
    if verb == "skills":
        _fastfold_skills(rest)
        return
    if verb == "log":
        _fastfold_log(rest)
        return
    if verb == "undo":
        _fastfold_undo()
        return
    if verb == "reset":
        _fastfold_reset()
        return
    if verb == "dry":
        prompt = " ".join(rest).strip()
        if not prompt:
            print("Usage: fastfold dry <prompt>")
            return
        _run_prompt(prompt, dry=True)
        return
    if verb == "save":
        _fastfold_save(rest)
        return

    # Default behavior: everything is prompt text.
    _run_prompt(raw)


def _agent_command(*args, **kwargs):
    raw = " ".join(str(a) for a in args).strip()
    if not raw:
        print("Usage: agent <message>  (or: fastfold agent on|off|status)")
        return
    tokens = _tokenize(raw)
    if len(tokens) == 1 and tokens[0].lower() in ("on", "off", "status", "help"):
        _fastfold_agent(tokens)
        return
    _run_prompt(raw)


def _fastfold_ui() -> None:
    try:
        from .gui import show_dialog

        show_dialog(run_prompt=_run_prompt)
    except Exception as e:
        print(f"FastFold Agent: unable to open UI window — {e}")


# ── Core prompt runner ────────────────────────────────────────────────────────
def _run_prompt(
    prompt: str,
    dry: bool = False,
    save: bool = False,
    save_filename: Optional[str] = None,
    output_dir: str = "",
    model_override: Optional[str] = None,
    on_token=None,
) -> None:
    global _LAST_SCRIPT, _UNDO_STATE, _LAST_EXECUTION_NOTE

    from . import llm, session, state, skills
    from . import config
    from .prompts import SYSTEM_PROMPT
    from .utils import execute_code, parse_response

    cfg = config.load_config()
    sess = session.get_session()
    sess.max_history = int(cfg.get("max_history", 20))

    workflow_request = _is_fastfold_workflow_prompt(prompt)

    # Ensure generated code can use FASTFOLD_API_KEY consistently.
    configured_ff_key = (cfg.get("fastfold_api_key") or "").strip()
    if configured_ff_key and not os.environ.get("FASTFOLD_API_KEY"):
        os.environ["FASTFOLD_API_KEY"] = configured_ff_key
    effective_ff_key = (os.environ.get("FASTFOLD_API_KEY") or "").strip()

    if workflow_request and not effective_ff_key:
        print("FastFold Agent: FastFold API key is required for workflow requests.")
        print("Run: fastfold setup")
        _LAST_EXECUTION_NOTE = ""
        return

    resolved_dir = os.path.expanduser(output_dir or cfg.get("output_dir") or os.getcwd())
    if not os.path.exists(resolved_dir):
        print(f"FastFold Agent: output directory '{resolved_dir}' does not exist — creating it.")
    os.makedirs(resolved_dir, exist_ok=True)

    scene = state.get_scene_state()
    exec_note = (
        f"\n\nNote from previous command: {_LAST_EXECUTION_NOTE}"
        if _LAST_EXECUTION_NOTE
        else ""
    )
    user_msg = (
        f"{scene}{exec_note}"
        f"\n\nOutput directory for any saved files: {resolved_dir}"
        f"\n\nUser request: {prompt}"
    )

    skills_context = ""
    if cfg.get("skills_enabled", True):
        skills_context = skills.build_context_for_prompt(
            prompt,
            max_chars=int(cfg.get("skills_max_chars", 10000)),
        )
    system_prompt = SYSTEM_PROMPT
    if skills_context:
        system_prompt = f"{SYSTEM_PROMPT}\n\n{skills_context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages += sess.get_messages()
    messages.append({"role": "user", "content": user_msg})

    backend = cfg.get("backend", "anthropic")
    if model_override:
        print(f"FastFold Agent [{backend}]: thinking (model: {model_override})...")
    else:
        print(f"FastFold Agent [{backend}]: thinking...")

    try:
        response = llm.chat(messages, on_token=on_token, model_override=model_override)
    except RuntimeError as e:
        print(f"FastFold Agent ERROR: {e}")
        _LAST_EXECUTION_NOTE = ""
        return

    summary, code = parse_response(response)

    if code:
        _LAST_SCRIPT = code

        if dry:
            print(f"--- Generated commands (dry run) [outdir: {resolved_dir}] ---")
            for line in code.splitlines():
                print(f"  {line}")
            print("--- End dry run ---")
            _LAST_EXECUTION_NOTE = ""
        else:
            _save_undo_state()
            try:
                from pymol import cmd as _cmd

                objects_before = set(_cmd.get_object_list() or [])
            except Exception:
                objects_before = set()

            print(f"--- Executing [outdir: {resolved_dir}] ---")
            error = execute_code(code, resolved_dir)

            if error:
                print(f"FastFold Agent: execution error — {error}")
                print("FastFold Agent: asking LLM to fix once...")
                retry_messages = messages + [
                    {"role": "assistant", "content": response},
                    {
                        "role": "user",
                        "content": (
                            f"The code raised this error:\n\n    {error}\n\n"
                            "Please fix it and try again."
                        ),
                    },
                ]
                try:
                    response2 = llm.chat(
                        retry_messages,
                        on_token=on_token,
                        model_override=model_override,
                    )
                    _, code2 = parse_response(response2)
                    if code2:
                        error2 = execute_code(code2, resolved_dir)
                        if error2:
                            print(f"FastFold Agent: auto-fix also failed — {error2}")
                            _LAST_EXECUTION_NOTE = (
                                f"Code failed ({error}). Auto-fix also failed ({error2})."
                            )
                        else:
                            print("--- Done (auto-fixed) ---")
                            code = code2
                            response = response2
                            _LAST_EXECUTION_NOTE = (
                                "Previous code had an error that was auto-fixed."
                            )
                    else:
                        print("FastFold Agent: retry did not produce code.")
                        _LAST_EXECUTION_NOTE = f"Code failed with error: {error}"
                except RuntimeError as retry_err:
                    print(f"FastFold Agent: retry LLM call failed — {retry_err}")
                    _LAST_EXECUTION_NOTE = f"Code failed with error: {error}"
            else:
                try:
                    objects_after = set(_cmd.get_object_list() or [])
                    added = objects_after - objects_before
                    removed = objects_before - objects_after
                    notes = []
                    if added:
                        notes.append(f"added {', '.join(sorted(added))}")
                    if removed:
                        notes.append(f"removed {', '.join(sorted(removed))}")
                    change_str = "; ".join(notes) if notes else "no object changes"
                    _LAST_EXECUTION_NOTE = f"Executed successfully. Scene: {change_str}."
                except Exception:
                    _LAST_EXECUTION_NOTE = "Executed successfully."
                print("--- Done ---")

        if save:
            _do_save(code, save_filename, resolved_dir)
    else:
        _LAST_EXECUTION_NOTE = ""

    sess.add_user(f"User request: {prompt}")
    sess.add_assistant(response)
    sess.log_exchange(prompt, summary, code if code else None)

    # PyMOL interprets bare text as Python. When the assistant asks for more
    # details in plain text, remind the user to prefix the next turn with ff.
    if not code and _looks_like_followup_request(summary):
        if cfg.get("agent_mode", False):
            print("\nFastFold Agent tip: reply with `agent <message>` (or `ff \"...\"`).")
        else:
            print(
                "\nFastFold Agent tip: reply with `ff \"...\"` / `fastfold \"...\"` / `agent <message>`.\n"
                "Enable sticky agent mode anytime: `fastfold agent on`."
            )


def _is_fastfold_workflow_prompt(prompt: str) -> bool:
    text = prompt.lower()
    return any(k in text for k in _WORKFLOW_KEYWORDS)


def _looks_like_followup_request(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    patterns = (
        r"\bplease provide\b",
        r"\bi need\b",
        r"\bcould you\b",
        r"\bshare\b",
        r"\bwhat would you like\b",
        r"\bonce you provide\b",
        r"\brequired information\b",
    )
    return any(re.search(p, t) for p in patterns) or t.endswith("?")


def _fastfold_agent(tokens: list[str]) -> None:
    from . import config

    subcommand = tokens[0].lower() if tokens else "status"
    if subcommand in ("status", "show"):
        enabled = bool(config.get("agent_mode"))
        print(f"FastFold Agent mode: {'ON' if enabled else 'OFF'}")
        print("Use `agent <message>` for conversational turns.")
        print("Use `fastfold agent on` or `fastfold agent off` to toggle.")
        return

    if subcommand in ("on", "enable"):
        config.save_config("agent_mode", True)
        print("FastFold Agent mode: ON")
        print("You can now use `agent <message>` for follow-up turns.")
        return

    if subcommand in ("off", "disable"):
        config.save_config("agent_mode", False)
        print("FastFold Agent mode: OFF")
        print("Use `ff \"...\"` or `fastfold \"...\"` as usual.")
        return

    # Treat anything else as a direct agent prompt payload.
    prompt = " ".join(tokens).strip()
    if not prompt:
        print("Usage: fastfold agent on|off|status OR fastfold agent <message>")
        return
    _run_prompt(prompt)


# ── Undo helpers ──────────────────────────────────────────────────────────────
def _save_undo_state() -> None:
    global _UNDO_STATE
    try:
        from pymol import cmd

        _UNDO_STATE = cmd.get_session()
    except Exception:
        _UNDO_STATE = None


def _fastfold_undo():
    global _UNDO_STATE
    if _UNDO_STATE is None:
        print("FastFold Agent: nothing to undo.")
        return
    try:
        from pymol import cmd

        cmd.set_session(_UNDO_STATE)
        _UNDO_STATE = None
        print("FastFold Agent: scene restored to before last command.")
    except Exception as e:
        print(f"FastFold Agent: undo failed — {e}")


def _fastfold_reset():
    global _LAST_SCRIPT, _UNDO_STATE, _LAST_EXECUTION_NOTE
    from . import session

    session.reset_session()
    _LAST_SCRIPT = None
    _UNDO_STATE = None
    _LAST_EXECUTION_NOTE = ""
    print("FastFold Agent: conversation history cleared.")


# ── setup/config command group ────────────────────────────────────────────────
def _store_credentials(anthropic_key: str, fastfold_key: str) -> None:
    from . import config

    config.save_config("backend", "anthropic")
    config.save_config("anthropic_use_agent_sdk", True)
    if anthropic_key:
        config.save_config("anthropic_api_key", anthropic_key)
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    if fastfold_key:
        config.save_config("fastfold_api_key", fastfold_key)
        os.environ["FASTFOLD_API_KEY"] = fastfold_key


def _fastfold_setup(tokens: list[str]) -> None:
    from . import config

    cfg = config.load_config()
    existing_anthropic = (cfg.get("anthropic_api_key") or "").strip()
    existing_fastfold = (cfg.get("fastfold_api_key") or "").strip()

    if not tokens:
        _print_setup_wizard(first_run=False)
        return

    # Non-interactive one-shot: fastfold setup <anthropic_key> <fastfold_key>
    if (
        len(tokens) >= 2
        and tokens[0].lower() not in ("anthropic", "fastfold")
    ):
        anthropic_key = tokens[0].strip()
        fastfold_key = " ".join(tokens[1:]).strip()
        if not anthropic_key or not fastfold_key:
            print("Usage: fastfold setup <anthropic_key> <fastfold_key>")
            return
        _store_credentials(anthropic_key, fastfold_key)
        print("\nFastFold Agent: setup complete.")
        print("Run `fastfold doctor` to verify everything.\n")
        return

    target = tokens[0].lower()
    key = " ".join(tokens[1:]).strip() if len(tokens) > 1 else ""

    if target == "anthropic":
        if not key:
            print("\nUsage: fastfold setup anthropic <your-api-key>")
            print(
                "Current Anthropic key: "
                + ("configured" if existing_anthropic else "missing")
                + "\n"
            )
            return
        _store_credentials(key, existing_fastfold)
        print("\nFastFold Agent: Anthropic API key saved.")
        print("Run `fastfold doctor` to verify everything.\n")
        return

    if target == "fastfold":
        if not key:
            print("\nUsage: fastfold setup fastfold <your-api-key>")
            print(
                "Current FastFold key: "
                + ("configured" if existing_fastfold else "missing")
                + "\n"
            )
            return
        _store_credentials(existing_anthropic, key)
        print("\nFastFold Agent: FastFold API key saved.")
        print("Run `fastfold doctor` to verify everything.\n")
        return

    print(
        f"Unknown setup target '{target}'.\n"
        "Use one of:\n"
        "  fastfold setup\n"
        "  fastfold setup <anthropic_key> <fastfold_key>\n"
        "  fastfold setup anthropic [key]\n"
        "  fastfold setup fastfold [key]"
    )


def _print_setup_wizard(first_run: bool = False) -> None:
    from . import config

    has_anthropic = bool((config.get("anthropic_api_key") or "").strip())
    has_fastfold = bool((config.get("fastfold_api_key") or "").strip())
    if first_run:
        print("")
        print("  ╔══════════════════════════════════════════════════╗")
        print("  ║           Welcome to FastFold Agent              ║")
        print("  ║          Natural-language control for PyMOL      ║")
        print("  ╚══════════════════════════════════════════════════╝")
        print("")
        print("  First-time setup — configure required API keys:")
    else:
        print("\n  FastFold Agent Setup")
        print("  " + "─" * 48)
        print("\n  Configure Anthropic + FastFold API keys:")

    print("")
    print(f"  Anthropic API key: {'configured' if has_anthropic else 'missing'}")
    print(f"  FastFold API key:  {'configured' if has_fastfold else 'missing'}")
    print("")
    print("  Run guided setup (non-blocking):")
    print("       fastfold setup")
    print("")
    print("  Set both keys in one command:")
    print("       fastfold setup <anthropic-key> <fastfold-key>")
    print("")
    print("  Update only one key:")
    print("       fastfold setup anthropic <key>")
    print("       fastfold setup fastfold <key>")
    print("")
    print("  ─────────────────────────────────────────────────────")
    print("  Run `fastfold doctor` after setup to validate everything.")
    print("  Type 'fastfold help' for all commands.")
    print("  Type 'fastfold config show' to view settings.\n")


def _parse_config_value(key: str, raw_value: str):
    if key in ("max_history", "skills_max_chars", "agent_sdk_max_turns"):
        return int(raw_value)
    if key in ("skills_enabled", "skills_auto_reload", "anthropic_use_agent_sdk", "agent_mode"):
        return raw_value.lower() in ("1", "true", "yes", "on")
    if key == "skills_paths":
        return [v.strip() for v in raw_value.split(",") if v.strip()]
    return raw_value


def _fastfold_config(tokens: list[str]) -> None:
    from . import config
    from . import session

    if not tokens or tokens[0].lower() == "show":
        cfg = config.load_config()
        print("FastFold Agent config:")
        for key in sorted(cfg):
            value = cfg[key]
            if "key" in key and value:
                value = "***"
            print(f"  {key} = {value}")
        return

    if tokens[0].lower() != "set" or len(tokens) < 3:
        print("Usage: fastfold config show | fastfold config set <key> <value>")
        return

    key = tokens[1]
    raw_value = " ".join(tokens[2:])
    if key not in config.DEFAULTS:
        valid = ", ".join(sorted(config.DEFAULTS.keys()))
        print(f"Unknown config key '{key}'. Valid keys: {valid}")
        return

    if key == "backend" and raw_value != "anthropic":
        print("backend is fixed to: anthropic")
        return
    if key == "sidecar_mode" and raw_value not in ("off", "optional", "required"):
        print("sidecar_mode must be one of: off, optional, required")
        return

    try:
        value = _parse_config_value(key, raw_value)
    except ValueError as e:
        print(f"Invalid value for {key}: {e}")
        return

    config.save_config(key, value)
    if key == "max_history":
        session.update_max_history(int(value))
    print(f"FastFold Agent: set {key} = {value}")


def _fastfold_doctor() -> None:
    from . import config, skills

    cfg = config.load_config()
    print("FastFold Agent doctor:")

    failures = 0

    def check(ok: bool, name: str, detail_ok: str = "", detail_fail: str = "") -> None:
        nonlocal failures
        status = "OK" if ok else "FAIL"
        detail = detail_ok if ok else detail_fail
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures += 1

    backend = str(cfg.get("backend") or "")
    check(
        backend == "anthropic",
        "Backend",
        detail_ok="anthropic",
        detail_fail=f"current value is '{backend}'. Run `fastfold setup`.",
    )

    anthropic_cfg = (cfg.get("anthropic_api_key") or "").strip()
    anthropic_env = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    check(
        bool(anthropic_cfg or anthropic_env),
        "Anthropic API key",
        detail_ok="configured",
        detail_fail="missing. Run `fastfold setup`.",
    )

    fastfold_cfg = (cfg.get("fastfold_api_key") or "").strip()
    fastfold_env = (os.environ.get("FASTFOLD_API_KEY") or "").strip()
    check(
        bool(fastfold_cfg or fastfold_env),
        "FastFold API key",
        detail_ok="configured",
        detail_fail="missing. Run `fastfold setup`.",
    )

    sdk_enabled = bool(cfg.get("anthropic_use_agent_sdk", True))
    check(
        sdk_enabled,
        "Claude Agent SDK mode",
        detail_ok="enabled",
        detail_fail="disabled. Run `fastfold config set anthropic_use_agent_sdk true`.",
    )

    anthropic_ok = importlib.util.find_spec("anthropic") is not None
    anthropic_err = "anthropic package not installed"
    check(
        anthropic_ok,
        "anthropic package",
        detail_ok="importable",
        detail_fail=f"not importable ({anthropic_err}). Reinstall package.",
    )

    sdk_pkg_ok = importlib.util.find_spec("claude_agent_sdk") is not None
    sdk_pkg_err = "claude-agent-sdk package not installed"
    check(
        sdk_pkg_ok,
        "claude-agent-sdk package",
        detail_ok="importable",
        detail_fail=f"not importable ({sdk_pkg_err}). Reinstall package.",
    )

    fold_skill = skills.find_skill("fold")
    check(
        fold_skill is not None,
        "Fold skill discovery",
        detail_ok="found",
        detail_fail="missing. Ensure fold skill exists under configured skills_paths.",
    )

    if fold_skill:
        fold_dir = os.path.dirname(fold_skill.path)
        required_scripts = ("create_job.py", "wait_for_completion.py", "download_cif.py")
        missing = []
        for script_name in required_scripts:
            script_path = os.path.join(fold_dir, "scripts", script_name)
            if not os.path.isfile(script_path):
                missing.append(script_name)
        check(
            not missing,
            "Fold skill scripts",
            detail_ok="create/wait/download scripts present",
            detail_fail=f"missing: {', '.join(missing)}",
        )

    if failures == 0:
        print("\nDoctor result: healthy setup.")
    else:
        print(f"\nDoctor result: {failures} issue(s) found.")


# ── skills command group ──────────────────────────────────────────────────────
def _fastfold_skills(tokens: list[str]) -> None:
    from . import skills

    subcommand = tokens[0].lower() if tokens else "list"
    args = tokens[1:]

    if subcommand == "reload":
        reloaded = skills.reload_skills()
        print(f"FastFold Agent: reloaded {len(reloaded)} skill(s).")
        return

    if subcommand == "list":
        discovered = skills.list_skills()
        if not discovered:
            print("No skills discovered. Add skill folders under configured skills_paths.")
            return
        print(f"Discovered {len(discovered)} skill(s):")
        for skill in discovered:
            desc = skill.description or "(no description)"
            print(f"  - {skill.name} [{skill.skill_type}]")
            print(f"      {desc}")
            print(f"      path: {skill.path}")
        return

    if subcommand == "show":
        if not args:
            print("Usage: fastfold skills show <skill_name>")
            return
        skill = skills.find_skill(args[0])
        if not skill:
            print(f"Skill not found: {args[0]}")
            return
        print(f"Skill: {skill.name}")
        print(f"Type: {skill.skill_type}")
        print(f"Path: {skill.path}")
        print(f"Description: {skill.description or '(none)'}")
        tags = skill.metadata.get("tags", [])
        if tags:
            print(f"Tags: {', '.join(str(t) for t in tags)}")
        for heading in ("Overview", "When to Use This Skill", "When to Use", "Workflow", "Running Scripts"):
            section = skill.sections.get(heading)
            if section:
                print(f"\n## {heading}\n{section}")
        return

    if subcommand == "howto":
        if not args:
            print("Usage: fastfold skills howto <skill_name>")
            return
        skill = skills.find_skill(args[0])
        if not skill:
            print(f"Skill not found: {args[0]}")
            return
        print(f"How to use '{skill.name}':")
        if skill.usage_examples:
            for idx, example in enumerate(skill.usage_examples[:3], 1):
                print(f"\nExample {idx}:\n{example}")
            return
        workflow = skill.sections.get("Workflow")
        if workflow:
            print(workflow)
            return
        print("No explicit usage examples found in SKILL.md.")
        return

    if subcommand == "search":
        query = " ".join(args).strip()
        if not query:
            print("Usage: fastfold skills search <query>")
            return
        hits = skills.search_skills(query)
        if not hits:
            print(f"No skills matched query '{query}'.")
            return
        print(f"Skills matching '{query}':")
        for skill in hits:
            print(f"  - {skill.name}: {skill.description}")
        return

    print("Usage: fastfold skills list|show|howto|reload|search")


# ── save/log helpers ──────────────────────────────────────────────────────────
def _looks_like_filename(s: str) -> bool:
    return "." in s and len(s.split()) == 1


def _fastfold_save(tokens: list[str]) -> None:
    global _LAST_SCRIPT
    from . import config

    # No args: save last generated script.
    if not tokens:
        if _LAST_SCRIPT is None:
            print("FastFold Agent: no script has been generated yet.")
            return
        out = os.path.expanduser(config.get("output_dir") or os.getcwd())
        _do_save(_LAST_SCRIPT, None, out)
        return

    # filename + prompt => run and save generated script.
    if len(tokens) > 1 and _looks_like_filename(tokens[0]):
        filename = tokens[0]
        prompt = " ".join(tokens[1:]).strip()
        if not prompt:
            if _LAST_SCRIPT is None:
                print("FastFold Agent: no script has been generated yet.")
                return
            out = os.path.expanduser(config.get("output_dir") or os.getcwd())
            _do_save(_LAST_SCRIPT, filename, out)
            return
        _run_prompt(prompt, save=True, save_filename=filename)
        return

    # one token: either filename for save-last or one-word prompt
    if len(tokens) == 1 and _looks_like_filename(tokens[0]):
        if _LAST_SCRIPT is None:
            print("FastFold Agent: no script has been generated yet.")
            return
        out = os.path.expanduser(config.get("output_dir") or os.getcwd())
        _do_save(_LAST_SCRIPT, tokens[0], out)
        return

    # otherwise treat as prompt and save auto-named file
    prompt = " ".join(tokens).strip()
    if not prompt:
        print("Usage: fastfold save [filename.py] <prompt>")
        return
    _run_prompt(prompt, save=True)


def _do_save(code: str, filename: Optional[str], output_dir: str = "") -> None:
    if not filename:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"fastfold_pymol_agent_{ts}.py"
    base = output_dir or os.getcwd()
    try:
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, filename)
        _write_script(path, code)
    except OSError:
        scripts_dir = os.path.expanduser("~/.fastfold-pymol-agent/scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        path = os.path.join(scripts_dir, filename)
        _write_script(path, code)


def _write_script(path: str, code: str) -> None:
    header = (
        "# Generated by FastFold PyMOL Agent\n"
        f"# {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "from pymol import cmd\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + code + "\n")
    print(f"FastFold Agent: script saved to {path}")


def _fastfold_log(tokens: list[str]) -> None:
    from . import session, config as cfg_mod

    subcommand = tokens[0] if tokens else "show"
    sess = session.get_session()
    log = sess.get_log()

    if not log:
        print("FastFold Agent: no exchanges in this session yet.")
        return

    if subcommand == "show":
        print(f"FastFold session log (started {sess.started_at}):")
        for i, entry in enumerate(log, 1):
            print(f"\n--- [{i}] {entry['timestamp']} ---")
            print(f"  Prompt : {entry['prompt']}")
            if entry["summary"]:
                print(f"  Summary: {entry['summary']}")
            if entry["code"]:
                for line in entry["code"].splitlines():
                    print(f"    {line}")
        return

    out = os.path.expanduser(cfg_mod.get("output_dir") or os.getcwd())

    if subcommand == "save":
        filename = tokens[1] if len(tokens) > 1 else None
        _save_session_log(sess, log, filename, out)
        return

    if subcommand == "export":
        filename = tokens[1] if len(tokens) > 1 else None
        if not filename:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"fastfold_pymol_agent_session_{ts}.json"
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, filename) if not os.path.isabs(filename) else filename
        data = {
            "started_at": sess.started_at,
            "exported_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exchanges": log,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"FastFold Agent: session exported to {path}")
        return

    print("Usage: fastfold log show|save [file.py]|export [file.json]")


def _save_session_log(sess, log: list, filename: Optional[str], output_dir: str = "") -> None:
    if filename and os.path.isabs(filename):
        path = filename
    else:
        base = output_dir or os.getcwd()
        if not filename:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"fastfold_pymol_agent_session_{ts}.py"
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, filename)

    lines = [
        "# FastFold PyMOL Agent session log",
        f"# Session started: {sess.started_at}",
        f"# Saved:           {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "from pymol import cmd",
        "",
    ]
    for i, entry in enumerate(log, 1):
        lines.append(f"# ── Step {i}: {entry['timestamp']}")
        lines.append(f"# Prompt: {entry['prompt']}")
        if entry["summary"]:
            lines.append(f"# {entry['summary']}")
        lines.append(entry["code"] if entry["code"] else "# (no commands generated)")
        lines.append("")

    content = "\n".join(lines)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        fallback_base = os.path.expanduser("~/.fastfold-pymol-agent/scripts")
        os.makedirs(fallback_base, exist_ok=True)
        fallback = os.path.join(fallback_base, os.path.basename(path))
        with open(fallback, "w", encoding="utf-8") as f:
            f.write(content)
        path = fallback

    print(f"FastFold Agent: session log saved to {path}")


def _print_help() -> None:
    print(
        "FastFold PyMOL Agent usage:\n"
        "  fastfold <prompt>                     ask the LLM and auto-execute\n"
        "  fastfold ui                           open multiline FastFold Agent window\n"
        "  fastfold dry <prompt>                 preview generated commands\n"
        "  fastfold save [file.py] <prompt>      run prompt and save script\n"
        "  fastfold save [file.py]               save last generated script\n"
        "  fastfold undo                         restore scene before last command\n"
        "  fastfold reset                        clear conversation history and undo state\n"
        "\n"
        "  fastfold setup                        guided setup (non-blocking)\n"
        "  fastfold setup <anthropic> <fastfold> non-interactive one-shot setup\n"
        "  fastfold setup anthropic <key>        update Anthropic key\n"
        "  fastfold setup fastfold <key>         update FastFold key\n"
        "  fastfold doctor                       verify setup health (keys, deps, skills)\n"
        "  fastfold agent on|off|status          toggle/show agent mode\n"
        "\n"
        "  fastfold config show                  show current config\n"
        "  fastfold config set <key> <value>     set any config key\n"
        "\n"
        "  fastfold skills list                  list discovered skills\n"
        "  fastfold skills show <name>           show skill details\n"
        "  fastfold skills howto <name>          show usage examples\n"
        "  fastfold skills search <query>        search skills by text\n"
        "  fastfold skills reload                rescan skill directories\n"
        "\n"
        "  fastfold log show                     print session log to console\n"
        "  fastfold log save [file.py]           save session as runnable script\n"
        "  fastfold log export [file.json]       export session as JSON\n"
        "\n"
        "  agent <message>                       conversational alias for follow-up turns\n"
        "  ff <...>                              short alias for fastfold\n"
    )
