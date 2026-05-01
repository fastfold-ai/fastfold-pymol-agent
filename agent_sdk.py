from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Callable, Optional

from . import config, skills


def _tool_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, indent=2)
    except Exception:
        return str(payload)


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _tool_text(payload)}],
        "is_error": is_error,
    }


def _resolve_skill_dir(skill_name: str) -> str:
    skill = skills.find_skill(skill_name)
    if not skill:
        raise ValueError(f"Skill not found: {skill_name}")
    return os.path.dirname(skill.path)


def _resolve_fold_skill_dir() -> str:
    try:
        return _resolve_skill_dir("fold")
    except Exception:
        fallback = os.path.expanduser("~/.fastfold-pymol-agent/skills/fold")
        if not os.path.isdir(fallback):
            raise ValueError(
                "Fold skill not found. Add it under ~/.fastfold-pymol-agent/skills/fold."
            )
        return fallback


def _safe_script_path(skill_dir: str, script_name: str) -> str:
    scripts_root = os.path.realpath(os.path.join(skill_dir, "scripts"))
    if not os.path.isdir(scripts_root):
        raise ValueError(f"Skill has no scripts directory: {skill_dir}")
    script_path = os.path.realpath(os.path.join(scripts_root, script_name))
    if not script_path.startswith(scripts_root + os.sep):
        raise ValueError(f"Invalid script path: {script_name}")
    if not os.path.isfile(script_path):
        raise ValueError(f"Script not found: {script_name}")
    return script_path


def _safe_relative_file_path(root_dir: str, relative_path: str) -> str:
    if not relative_path:
        raise ValueError("Path is required.")
    root_real = os.path.realpath(root_dir)
    path_real = os.path.realpath(os.path.join(root_real, relative_path))
    if not path_real.startswith(root_real + os.sep):
        raise ValueError(f"Invalid path outside allowed root: {relative_path}")
    if not os.path.isfile(path_real):
        raise ValueError(f"File not found: {relative_path}")
    return path_real


def _prepare_env() -> dict[str, str]:
    env = dict(os.environ)
    ff_key = (config.get("fastfold_api_key") or "").strip()
    if ff_key and not env.get("FASTFOLD_API_KEY"):
        env["FASTFOLD_API_KEY"] = ff_key
    return env


async def _run_script(
    *,
    skill_dir: str,
    script_name: str,
    args: list[str],
    stdin_text: str = "",
    timeout_s: int = 1800,
) -> dict[str, Any]:
    script_path = _safe_script_path(skill_dir, script_name)
    proc_args = [sys.executable, script_path] + [str(a) for a in args]

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            proc_args,
            cwd=skill_dir,
            env=_prepare_env(),
            input=stdin_text if stdin_text else None,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_s)),
        )

    try:
        result = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"Timed out after {timeout_s}s.",
            "cmd": proc_args,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": proc_args}

    return {
        "ok": result.returncode == 0,
        "return_code": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "cmd": proc_args,
    }


def _json_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _line_list(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def create_fastfold_mcp_server():
    try:
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server
    except ImportError as e:
        raise RuntimeError(
            "claude-agent-sdk is not installed. Run: pip install claude-agent-sdk"
        ) from e

    async def skill_list_handler(_args: dict[str, Any]) -> dict[str, Any]:
        items = skills.list_skills(force_reload=False)
        payload = [
            {
                "name": item.name,
                "description": item.description,
                "type": item.skill_type,
                "path": item.path,
            }
            for item in items
        ]
        return _tool_result({"skills": payload})

    async def skill_load_handler(args: dict[str, Any]) -> dict[str, Any]:
        skill_name = str(args.get("skill_name", "")).strip()
        if not skill_name:
            return _tool_result("Missing required field: skill_name", is_error=True)
        item = skills.find_skill(skill_name)
        if not item:
            return _tool_result(f"Skill not found: {skill_name}", is_error=True)
        payload = {
            "name": item.name,
            "description": item.description,
            "type": item.skill_type,
            "path": item.path,
            "content": item.content,
            "usage_examples": item.usage_examples,
            "sections": item.sections,
        }
        return _tool_result(payload)

    async def skill_run_script_handler(args: dict[str, Any]) -> dict[str, Any]:
        skill_name = str(args.get("skill_name", "")).strip()
        script_name = str(args.get("script_name", "")).strip()
        raw_args = args.get("args", [])
        stdin_text = str(args.get("stdin_text", "") or "")
        timeout_s = int(args.get("timeout_s", 1800))

        if not skill_name or not script_name:
            return _tool_result(
                "Missing required fields: skill_name and script_name",
                is_error=True,
            )
        if not isinstance(raw_args, list):
            return _tool_result("args must be an array of strings", is_error=True)

        try:
            skill_dir = _resolve_skill_dir(skill_name)
        except Exception as e:
            return _tool_result(str(e), is_error=True)

        run = await _run_script(
            skill_dir=skill_dir,
            script_name=script_name,
            args=[str(x) for x in raw_args],
            stdin_text=stdin_text,
            timeout_s=timeout_s,
        )
        return _tool_result(run, is_error=not run.get("ok", False))

    async def skill_list_files_handler(args: dict[str, Any]) -> dict[str, Any]:
        skill_name = str(args.get("skill_name", "")).strip()
        area = str(args.get("area", "references")).strip().lower()
        max_files = int(args.get("max_files", 200))
        if not skill_name:
            return _tool_result("Missing required field: skill_name", is_error=True)
        if area not in ("references", "scripts", "all"):
            return _tool_result(
                "Invalid area. Use one of: references, scripts, all.",
                is_error=True,
            )
        max_files = max(1, min(max_files, 2000))
        try:
            skill_dir = _resolve_skill_dir(skill_name)
        except Exception as e:
            return _tool_result(str(e), is_error=True)

        areas = ["references", "scripts"] if area == "all" else [area]
        files: list[str] = []
        truncated = False
        for segment in areas:
            base = os.path.realpath(os.path.join(skill_dir, segment))
            if not os.path.isdir(base):
                continue
            for root, _, names in os.walk(base):
                names.sort()
                for name in names:
                    abs_path = os.path.realpath(os.path.join(root, name))
                    rel_path = os.path.relpath(abs_path, skill_dir)
                    files.append(rel_path)
                    if len(files) >= max_files:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break

        payload = {
            "skill_name": skill_name,
            "area": area,
            "files": files,
            "count": len(files),
            "truncated": truncated,
        }
        return _tool_result(payload)

    async def skill_read_reference_handler(args: dict[str, Any]) -> dict[str, Any]:
        skill_name = str(args.get("skill_name", "")).strip()
        reference_path = str(args.get("reference_path", "")).strip()
        max_chars = int(args.get("max_chars", 60000))
        if not skill_name or not reference_path:
            return _tool_result(
                "Missing required fields: skill_name and reference_path",
                is_error=True,
            )
        max_chars = max(1000, min(max_chars, 200000))
        try:
            skill_dir = _resolve_skill_dir(skill_name)
            references_dir = os.path.realpath(os.path.join(skill_dir, "references"))
            if not os.path.isdir(references_dir):
                raise ValueError(f"Skill has no references directory: {skill_name}")
            file_path = _safe_relative_file_path(references_dir, reference_path)
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return _tool_result(str(e), is_error=True)

        total_chars = len(text)
        truncated = total_chars > max_chars
        content = text[:max_chars] if truncated else text
        payload = {
            "skill_name": skill_name,
            "reference_path": reference_path,
            "content": content,
            "total_chars": total_chars,
            "truncated": truncated,
        }
        return _tool_result(payload)

    async def fastfold_submit_wait_download_load_handler(
        args: dict[str, Any],
    ) -> dict[str, Any]:
        payload_json = str(args.get("payload_json", "")).strip()
        timeout_s = int(args.get("timeout_s", 1800))
        poll_interval_s = float(args.get("poll_interval_s", 5.0))
        object_prefix = str(args.get("object_prefix", "fastfold")).strip() or "fastfold"
        out_dir = str(args.get("output_dir", "")).strip()
        if not payload_json:
            return _tool_result("Missing required field: payload_json", is_error=True)

        parsed = _json_from_text(payload_json)
        if not isinstance(parsed, dict):
            return _tool_result("payload_json must be a JSON object", is_error=True)

        try:
            fold_skill_dir = _resolve_fold_skill_dir()
        except Exception as e:
            return _tool_result(str(e), is_error=True)

        create_run = await _run_script(
            skill_dir=fold_skill_dir,
            script_name="create_job.py",
            args=["--payload", "-"],
            stdin_text=payload_json,
            timeout_s=120,
        )
        if not create_run.get("ok"):
            return _tool_result(
                {"stage": "create_job", "result": create_run}, is_error=True
            )

        job_id = ""
        for line in reversed(_line_list(create_run.get("stdout", ""))):
            job_id = line
            break
        if not job_id:
            return _tool_result(
                {"stage": "create_job", "error": "No job id in create_job output", "result": create_run},
                is_error=True,
            )

        wait_run = await _run_script(
            skill_dir=fold_skill_dir,
            script_name="wait_for_completion.py",
            args=[
                job_id,
                "--poll-interval",
                str(poll_interval_s),
                "--timeout",
                str(timeout_s),
                "--json",
            ],
            timeout_s=max(timeout_s + 60, 120),
        )
        if not wait_run.get("ok"):
            return _tool_result(
                {"stage": "wait_for_completion", "job_id": job_id, "result": wait_run},
                is_error=True,
            )

        wait_json = _json_from_text(wait_run.get("stdout", "")) or {}

        if not out_dir:
            cfg_out = str(config.get("output_dir") or "").strip()
            out_dir = os.path.expanduser(cfg_out) if cfg_out else os.getcwd()
        out_dir = os.path.abspath(os.path.expanduser(out_dir))
        os.makedirs(out_dir, exist_ok=True)

        download_run = await _run_script(
            skill_dir=fold_skill_dir,
            script_name="download_cif.py",
            args=[job_id, "--dir", out_dir],
            timeout_s=600,
        )
        if not download_run.get("ok"):
            return _tool_result(
                {"stage": "download_cif", "job_id": job_id, "result": download_run},
                is_error=True,
            )

        downloaded_paths = _line_list(download_run.get("stdout", ""))
        if not downloaded_paths:
            return _tool_result(
                {
                    "stage": "download_cif",
                    "job_id": job_id,
                    "error": "No downloaded CIF paths found in script output",
                    "result": download_run,
                },
                is_error=True,
            )

        try:
            from pymol import cmd
        except Exception as e:
            return _tool_result(
                {
                    "stage": "pymol_load",
                    "job_id": job_id,
                    "downloaded_paths": downloaded_paths,
                    "error": f"PyMOL cmd unavailable: {e}",
                },
                is_error=True,
            )

        loaded_objects: list[str] = []
        for idx, path in enumerate(downloaded_paths, start=1):
            object_name = object_prefix if len(downloaded_paths) == 1 else f"{object_prefix}_{idx}"
            try:
                cmd.load(path, object_name)
                cmd.show("cartoon", object_name)
                loaded_objects.append(object_name)
            except Exception as e:
                return _tool_result(
                    {
                        "stage": "pymol_load",
                        "job_id": job_id,
                        "error": str(e),
                        "failed_path": path,
                        "loaded_objects": loaded_objects,
                    },
                    is_error=True,
                )
        try:
            if loaded_objects:
                cmd.util.cbc(" or ".join(loaded_objects))
        except Exception:
            pass

        payload = {
            "job_id": job_id,
            "status": (wait_json.get("job") or {}).get("status", "UNKNOWN"),
            "downloaded_paths": downloaded_paths,
            "loaded_objects": loaded_objects,
        }
        return _tool_result(payload)

    async def pymol_load_structure_handler(args: dict[str, Any]) -> dict[str, Any]:
        file_path = str(args.get("file_path", "")).strip()
        object_name = str(args.get("object_name", "")).strip()
        if not file_path:
            return _tool_result("Missing required field: file_path", is_error=True)
        resolved = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.isfile(resolved):
            return _tool_result(f"File not found: {resolved}", is_error=True)

        try:
            from pymol import cmd
        except Exception as e:
            return _tool_result(f"PyMOL cmd unavailable: {e}", is_error=True)

        obj = object_name or os.path.splitext(os.path.basename(resolved))[0]
        try:
            cmd.load(resolved, obj)
            cmd.show("cartoon", obj)
            cmd.util.cbc(obj)
        except Exception as e:
            return _tool_result(f"Failed to load structure: {e}", is_error=True)
        return _tool_result({"file_path": resolved, "object_name": obj})

    sdk_tools = [
        SdkMcpTool(
            name="skill_list",
            description="List discovered skills with names and descriptions.",
            input_schema={"type": "object", "properties": {}},
            handler=skill_list_handler,
        ),
        SdkMcpTool(
            name="skill_load",
            description="Load one skill's full instructions from SKILL.md.",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "Skill name"},
                },
                "required": ["skill_name"],
            },
            handler=skill_load_handler,
        ),
        SdkMcpTool(
            name="skill_run_script",
            description=(
                "Run a script from a skill folder. Use this for skill-backed workflows."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "script_name": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "stdin_text": {"type": "string"},
                    "timeout_s": {"type": "integer"},
                },
                "required": ["skill_name", "script_name"],
            },
            handler=skill_run_script_handler,
        ),
        SdkMcpTool(
            name="skill_list_files",
            description=(
                "List files from a skill's references/scripts so the agent can inspect the skill map."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "area": {
                        "type": "string",
                        "description": "references, scripts, or all",
                    },
                    "max_files": {"type": "integer"},
                },
                "required": ["skill_name"],
            },
            handler=skill_list_files_handler,
        ),
        SdkMcpTool(
            name="skill_read_reference",
            description=(
                "Read a file under a skill's references directory (safe relative paths only)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "reference_path": {
                        "type": "string",
                        "description": "Path relative to the skill references/ directory",
                    },
                    "max_chars": {"type": "integer"},
                },
                "required": ["skill_name", "reference_path"],
            },
            handler=skill_read_reference_handler,
        ),
        SdkMcpTool(
            name="fastfold_submit_wait_download_load",
            description=(
                "Preferred end-to-end FastFold workflow tool: submit job from payload JSON, "
                "wait for completion, download CIFs, and load them into PyMOL."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "payload_json": {
                        "type": "string",
                        "description": "Full FastFold JobInput JSON payload as a string.",
                    },
                    "timeout_s": {"type": "integer"},
                    "poll_interval_s": {"type": "number"},
                    "object_prefix": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
                "required": ["payload_json"],
            },
            handler=fastfold_submit_wait_download_load_handler,
        ),
        SdkMcpTool(
            name="pymol_load_structure",
            description="Load a local CIF/PDB structure file into PyMOL.",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "object_name": {"type": "string"},
                },
                "required": ["file_path"],
            },
            handler=pymol_load_structure_handler,
        ),
    ]

    server = create_sdk_mcp_server(
        name="fastfold-tools",
        version="1.0.0",
        tools=sdk_tools,
    )
    tool_names = [tool.name for tool in sdk_tools]
    return server, tool_names


async def run_claude_agent_sdk(
    messages: list[dict[str, str]],
    *,
    model: str,
    max_turns: int,
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            StreamEvent,
            TextBlock,
        )
    except ImportError as e:
        raise RuntimeError(
            "claude-agent-sdk is not installed. Run: pip install claude-agent-sdk"
        ) from e

    system_prompt = ""
    dialogue = []
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "system":
            system_prompt = content
            continue
        dialogue.append({"role": role, "content": content})

    if not dialogue:
        raise RuntimeError("No user messages to send.")

    last_user = ""
    history_lines: list[str] = []
    for msg in dialogue:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            last_user = content
        history_lines.append(f"{role.upper()}:\n{content}")

    if not last_user:
        last_user = dialogue[-1]["content"]
    history_text = "\n\n".join(history_lines[:-1]).strip()
    user_prompt = last_user
    if history_text:
        user_prompt = (
            "Conversation context (most recent first):\n"
            f"{history_text}\n\n"
            f"Current user request:\n{last_user}"
        )

    sdk_prompt = (
        "You can use MCP tools for skill-native execution.\n"
        "Inspect skill maps and references with `skill_list_files` and `skill_read_reference` when needed.\n"
        "For FastFold workflows, prefer tool calls over generating raw fallback code.\n"
        "Use `fastfold_submit_wait_download_load` for end-to-end fold execution when possible.\n"
        "If no tool is needed, you may still return a python code block for PyMOL actions.\n\n"
        f"{system_prompt}"
    )

    server, tool_names = create_fastfold_mcp_server()
    allowed_tools = [f"mcp__fastfold-tools__{name}" for name in tool_names]

    env = dict(os.environ)
    anthropic_key = (config.get("anthropic_api_key") or "").strip()
    if anthropic_key and not env.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = anthropic_key
    fastfold_key = (config.get("fastfold_api_key") or "").strip()
    if fastfold_key and not env.get("FASTFOLD_API_KEY"):
        env["FASTFOLD_API_KEY"] = fastfold_key

    options_kwargs = dict(
        system_prompt=sdk_prompt,
        model=model,
        max_turns=max(1, int(max_turns)),
        mcp_servers={"fastfold-tools": server},
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        env=env,
        hooks={},
    )

    try:
        options = ClaudeAgentOptions(include_partial_messages=True, **options_kwargs)
        partial_enabled = True
    except TypeError:
        options = ClaudeAgentOptions(**options_kwargs)
        partial_enabled = False

    streamed_chunks: list[str] = []
    full_text: list[str] = []

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_prompt)
        async for message in client.receive_response():
            if partial_enabled and isinstance(message, StreamEvent):
                event = getattr(message, "event", None) or {}
                if isinstance(event, dict):
                    delta = event.get("delta", {})
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        text = str(delta.get("text", ""))
                        if text:
                            streamed_chunks.append(text)
                            if on_token:
                                on_token(text)
                            else:
                                sys.stdout.write(text)
                                sys.stdout.flush()
                continue

            if isinstance(message, AssistantMessage):
                for block in message.content or []:
                    if isinstance(block, TextBlock):
                        text = block.text or ""
                        if text:
                            full_text.append(text)
                            if not partial_enabled:
                                if on_token:
                                    on_token(text)
                                else:
                                    sys.stdout.write(text)
                                    sys.stdout.flush()

    if not on_token:
        sys.stdout.write("\n")
        sys.stdout.flush()

    if full_text:
        return "".join(full_text)
    return "".join(streamed_chunks)
