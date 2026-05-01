from __future__ import annotations

import json
import os
from typing import Any

CONFIG_PATH = os.path.expanduser("~/.fastfold-pymol-agent.json")

DEFAULTS = {
    "backend": "lmstudio",
    "model": "local-model",
    "base_url": "http://localhost:1234/v1",
    "max_history": 20,
    "anthropic_model": "claude-sonnet-4-6",
    "openai_model": "gpt-4o",
    "anthropic_api_key": "",
    "openai_api_key": "",
    "fastfold_api_key": "",
    "output_dir": "",  # empty = use current working directory
    "skills_enabled": True,
    "skills_auto_reload": True,
    "skills_max_chars": 10000,
    "skills_paths": [
        os.path.expanduser("~/.fastfold-pymol-agent/skills"),
    ],
    "sidecar_mode": "off",
    "sidecar_endpoint": "",
    "fastfold_base_url": "https://api.fastfold.ai",
}

_LEGACY_CONFIG_PATH = os.path.expanduser("~/.promptmol.json")


def _coerce_types(data: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(data)
    if "max_history" in cfg:
        cfg["max_history"] = int(cfg["max_history"])
    if "skills_max_chars" in cfg:
        cfg["skills_max_chars"] = int(cfg["skills_max_chars"])
    if "skills_enabled" in cfg and isinstance(cfg["skills_enabled"], str):
        cfg["skills_enabled"] = cfg["skills_enabled"].lower() in ("1", "true", "yes", "on")
    if "skills_auto_reload" in cfg and isinstance(cfg["skills_auto_reload"], str):
        cfg["skills_auto_reload"] = cfg["skills_auto_reload"].lower() in ("1", "true", "yes", "on")
    if "skills_paths" in cfg:
        value = cfg["skills_paths"]
        if isinstance(value, str):
            cfg["skills_paths"] = [v.strip() for v in value.split(",") if v.strip()]
        elif isinstance(value, list):
            cfg["skills_paths"] = [str(v).strip() for v in value if str(v).strip()]
        else:
            cfg["skills_paths"] = list(DEFAULTS["skills_paths"])
    return cfg


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def load_config() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if os.path.exists(CONFIG_PATH):
        data = _read_json(CONFIG_PATH)
    elif os.path.exists(_LEGACY_CONFIG_PATH):
        # Hard rebrand keeps old values only as one-time source of truth.
        data = _read_json(_LEGACY_CONFIG_PATH)
        if "api_key" in data:
            # Best-effort migration from legacy single-key model.
            if data.get("backend") == "anthropic":
                data["anthropic_api_key"] = data["api_key"]
            elif data.get("backend") == "openai":
                data["openai_api_key"] = data["api_key"]
            del data["api_key"]
    cfg = dict(DEFAULTS)
    cfg.update(data)
    return _coerce_types(cfg)


def save_config(key: str, value: Any) -> None:
    cfg = load_config()
    cfg[key] = value
    cfg = _coerce_types(cfg)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get(key: str) -> Any:
    return load_config().get(key, DEFAULTS.get(key))
