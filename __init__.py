"""
FastFold PyMOL Agent — natural-language control for PyMOL.

Commands registered in the PyMOL command line:
  fastfold <prompt>
  fastfold dry <prompt>
  fastfold save [filename.py] <prompt>
  fastfold save [filename.py]            save last generated script
  fastfold undo
  fastfold reset
  fastfold setup lmstudio|openai|anthropic|fastfold [api_key]
  fastfold config show|set <key> <value>
  fastfold skills list|show|howto|reload|search
  fastfold log show|save|export [filename]
  fastfold help

Short alias:
  ff ... (same subcommands as fastfold)
"""

from __future__ import annotations

import datetime
import json
import os
import shlex
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

    if not os.path.exists(config.CONFIG_PATH):
        _print_setup_wizard(first_run=True)
    else:
        print("FastFold PyMOL Agent loaded. Type 'fastfold help' for usage.")
        print("Type 'fastfold skills list' to inspect installed skills.\n")


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
        print("Run: fastfold setup fastfold <your-api-key>")
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
    workflow_rules = _build_workflow_rules(prompt, cfg)
    if workflow_rules:
        system_prompt = f"{system_prompt}\n\n{workflow_rules}"

    messages = [{"role": "system", "content": system_prompt}]
    messages += sess.get_messages()
    messages.append({"role": "user", "content": user_msg})

    backend = cfg.get("backend", "lmstudio")
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


def _build_workflow_rules(prompt: str, cfg: dict) -> str:
    text = prompt.lower()
    if not any(k in text for k in _WORKFLOW_KEYWORDS):
        return ""
    has_key = bool((cfg.get("fastfold_api_key") or "").strip() or os.environ.get("FASTFOLD_API_KEY"))
    try:
        from . import skills as _skills

        fold_skill = _skills.find_skill("fold")
        fold_skill_dir = (
            os.path.dirname(fold_skill.path) if fold_skill else os.path.expanduser("~/.fastfold-pymol-agent/skills/fold")
        )
    except Exception:
        fold_skill_dir = os.path.expanduser("~/.fastfold-pymol-agent/skills/fold")
    scripts_dir = os.path.join(fold_skill_dir, "scripts")
    return (
        "## FastFold Workflow Rules (high priority)\n"
        "- This request appears to be a FastFold workflow request.\n"
        f"- Use installed fold skill scripts under `{scripts_dir}` for create/wait/results flows.\n"
        "- For `esm1b`, create the FastFold payload with `params.modelName = \"esm1b\"`.\n"
        "- For custom webhook requests, set `constraints.webhooks.custom_http.enabled = true`.\n"
        "- Use FastFold API credentials from `fastfold_api_key` / `FASTFOLD_API_KEY`.\n"
        "- Do NOT generate code that installs local folding libraries.\n"
        "- Do NOT use third-party fallback endpoints like `api.esmatlas.com`.\n"
        + (
            "- If API key is missing, return plain text asking user to run "
            "`fastfold setup fastfold <your-api-key>` and stop.\n"
            if not has_key
            else ""
        )
    ).strip()


def _is_fastfold_workflow_prompt(prompt: str) -> bool:
    text = prompt.lower()
    return any(k in text for k in _WORKFLOW_KEYWORDS)


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
def _fastfold_setup(tokens: list[str]) -> None:
    from . import config

    if not tokens:
        _print_setup_wizard(first_run=False)
        return

    target = tokens[0].lower()
    key = tokens[1] if len(tokens) > 1 else ""

    if target == "lmstudio":
        config.save_config("backend", "lmstudio")
        print("\n  FastFold Agent: backend set to LM Studio (local)")
        print(f"  Server URL: {config.get('base_url')}")
        print("  Optional tweaks:")
        print("    fastfold config set model <model-name>")
        print("    fastfold config set base_url <url>\n")
        print("  Setup complete! Try: fastfold fetch 1hpv and show as cartoon colored by chain")
        return

    if target == "openai":
        config.save_config("backend", "openai")
        if key:
            config.save_config("openai_api_key", key)
            print("\n  FastFold Agent: backend set to OpenAI, API key saved.")
            print(
                f"  Model: {config.get('openai_model')} "
                "(fastfold config set openai_model <name>)\n"
            )
            print("  Setup complete! Try: fastfold fetch 1hpv and show as cartoon colored by chain")
        else:
            print("\n  FastFold Agent: backend set to OpenAI.")
            print("  Enter your API key: fastfold setup openai <your-api-key>")
            print("  Get a key at: https://platform.openai.com/api-keys\n")
        return

    if target == "anthropic":
        config.save_config("backend", "anthropic")
        if key:
            config.save_config("anthropic_api_key", key)
            print("\n  FastFold Agent: backend set to Anthropic, API key saved.")
            print(
                f"  Model: {config.get('anthropic_model')} "
                "(fastfold config set anthropic_model <name>)\n"
            )
            print("  Setup complete! Try: fastfold fetch 1hpv and show as cartoon colored by chain")
        else:
            print("\n  FastFold Agent: backend set to Anthropic.")
            print("  Enter your API key: fastfold setup anthropic <your-api-key>")
            print("  Get a key at: https://console.anthropic.com/settings/keys\n")
        return

    if target == "fastfold":
        if key:
            config.save_config("fastfold_api_key", key)
            print("\n  FastFold Agent: FastFold API key saved.")
            print("  This key will be used by skill-backed workflow integrations.\n")
        else:
            print("\n  Usage: fastfold setup fastfold <your-api-key>")
            print("  Get a key at: https://cloud.fastfold.ai/api-keys\n")
        return

    print(f"Unknown setup target '{target}'. Choose: lmstudio, openai, anthropic, fastfold")


def _print_setup_wizard(first_run: bool = False) -> None:
    from . import config

    current = config.get("backend")
    if first_run:
        print("")
        print("  ╔══════════════════════════════════════════════════╗")
        print("  ║           Welcome to FastFold Agent              ║")
        print("  ║          Natural-language control for PyMOL      ║")
        print("  ╚══════════════════════════════════════════════════╝")
        print("")
        print("  First-time setup — choose your LLM backend:")
    else:
        print(f"\n  FastFold Agent Setup (current backend: {current})")
        print("  " + "─" * 48)
        print("\n  Choose a backend:")

    print("")
    print("  1. LM Studio  — local model, no API key needed")
    print("       fastfold setup lmstudio")
    print("")
    print("  2. OpenAI  — requires API key")
    print("       fastfold setup openai <your-api-key>")
    print("")
    print("  3. Anthropic  — requires API key")
    print("       fastfold setup anthropic <your-api-key>")
    print("")
    print("  4. FastFold API key for workflows")
    print("       fastfold setup fastfold <your-api-key>")
    print("")
    print("  ─────────────────────────────────────────────────────")
    print("  Type 'fastfold help' for all commands.")
    print("  Type 'fastfold config show' to view settings.\n")


def _parse_config_value(key: str, raw_value: str):
    if key in ("max_history", "skills_max_chars"):
        return int(raw_value)
    if key in ("skills_enabled", "skills_auto_reload"):
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

    if key == "backend" and raw_value not in ("lmstudio", "openai", "anthropic"):
        print("backend must be one of: lmstudio, openai, anthropic")
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
        "  fastfold dry <prompt>                 preview generated commands\n"
        "  fastfold save [file.py] <prompt>      run prompt and save script\n"
        "  fastfold save [file.py]               save last generated script\n"
        "  fastfold undo                         restore scene before last command\n"
        "  fastfold reset                        clear conversation history and undo state\n"
        "\n"
        "  fastfold setup lmstudio               switch to LM Studio backend\n"
        "  fastfold setup openai <key>           switch to OpenAI + set API key\n"
        "  fastfold setup anthropic <key>        switch to Anthropic + set API key\n"
        "  fastfold setup fastfold <key>         set FastFold API key\n"
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
        "  ff <...>                              short alias for fastfold\n"
    )
