"""Skill discovery and prompt-context helpers for FastFold PyMOL Agent."""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from typing import Any, Optional

from . import config


@dataclass
class SkillInfo:
    name: str
    description: str
    path: str
    content: str
    metadata: dict[str, Any]
    sections: dict[str, str]
    skill_type: str
    usage_examples: list[str]


_SKILL_CACHE: list[SkillInfo] | None = None


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    frontmatter = text[4:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, Any] = {}
    current_key: Optional[str] = None
    list_mode = False
    for raw in frontmatter.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and list_mode and current_key:
            value = stripped[2:].strip()
            meta.setdefault(current_key, [])
            meta[current_key].append(value)
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value:
                list_mode = False
                meta[key] = value
            else:
                list_mode = True
                meta[key] = []
    return meta, body


def _parse_sections(body: str) -> dict[str, str]:
    headers = list(re.finditer(r"^##\s+(.+)$", body, flags=re.MULTILINE))
    if not headers:
        return {}
    sections: dict[str, str] = {}
    for idx, match in enumerate(headers):
        title = match.group(1).strip()
        start = match.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(body)
        content = body[start:end].strip()
        sections[title] = content
    return sections


def _parse_code_blocks(body: str) -> list[str]:
    blocks = re.findall(r"```(?:bash|python|json)?\n(.*?)```", body, flags=re.DOTALL)
    return [b.strip() for b in blocks if b.strip()]


def _detect_skill_type(skill_dir: str) -> str:
    skill_json_path = os.path.join(skill_dir, "skill.json")
    if os.path.exists(skill_json_path):
        try:
            with open(skill_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return str(data.get("executor") or "instruction-only")
        except Exception:
            return "instruction-only"
    if os.path.isdir(os.path.join(skill_dir, "scripts")):
        return "script"
    return "instruction-only"


def _skill_paths() -> list[str]:
    cfg = config.load_config()
    raw = cfg.get("skills_paths", [])
    if isinstance(raw, str):
        paths = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, list):
        paths = [str(p).strip() for p in raw if str(p).strip()]
    else:
        paths = []
    expanded = []
    for path in paths:
        expanded.append(os.path.expanduser(path))
    return expanded


def reload_skills() -> list[SkillInfo]:
    global _SKILL_CACHE
    _SKILL_CACHE = _discover_skills()
    return list(_SKILL_CACHE)


def list_skills(force_reload: bool = False) -> list[SkillInfo]:
    global _SKILL_CACHE
    if force_reload or _SKILL_CACHE is None:
        _SKILL_CACHE = _discover_skills()
    return list(_SKILL_CACHE)


def find_skill(name: str) -> Optional[SkillInfo]:
    target = name.strip().lower()
    for skill in list_skills():
        if skill.name.lower() == target:
            return skill
    return None


def search_skills(query: str) -> list[SkillInfo]:
    q = query.strip().lower()
    if not q:
        return []
    hits: list[tuple[int, SkillInfo]] = []
    for skill in list_skills():
        text = f"{skill.name} {skill.description} {' '.join(skill.metadata.get('tags', []))}".lower()
        score = text.count(q)
        if score > 0:
            hits.append((score, skill))
    hits.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return [skill for _, skill in hits]


def build_context_for_prompt(prompt: str, max_chars: int = 10000) -> str:
    cfg = config.load_config()
    if not cfg.get("skills_enabled", True):
        return ""
    skills = _select_skills_for_prompt(prompt)
    if not skills:
        return ""
    parts = [
        "## Installed Skills\n"
        "Use the following skill instructions when relevant to the user request."
    ]
    budget = max(1000, int(max_chars))
    for skill in skills:
        section = f"\n\n### Skill: {skill.name}\n{skill.content}".strip()
        if len("\n".join(parts)) + len(section) > budget:
            break
        parts.append(section)
    return "\n".join(parts).strip()


def _select_skills_for_prompt(prompt: str, limit: int = 3) -> list[SkillInfo]:
    words = {w for w in re.findall(r"[a-zA-Z0-9_]+", prompt.lower()) if len(w) > 2}
    if not words:
        return []
    ranked: list[tuple[int, SkillInfo]] = []
    for skill in list_skills():
        hay = " ".join(
            [
                skill.name.lower(),
                skill.description.lower(),
                " ".join(str(t).lower() for t in skill.metadata.get("tags", [])),
            ]
        )
        score = 0
        for word in words:
            if word in hay:
                score += 2
            if word in skill.content.lower():
                score += 1
        if score > 0:
            ranked.append((score, skill))
    ranked.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return [skill for _, skill in ranked[:limit]]


def _discover_skills() -> list[SkillInfo]:
    found: list[SkillInfo] = []
    visited_names: set[str] = set()
    for base in _skill_paths():
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            if "SKILL.md" not in files:
                continue
            skill_md_path = os.path.join(root, "SKILL.md")
            raw = _read_text(skill_md_path)
            if not raw.strip():
                continue
            meta, body = _parse_frontmatter(raw)
            name = str(meta.get("name") or os.path.basename(root)).strip()
            if not name:
                continue
            key = name.lower()
            if key in visited_names:
                # First found wins by path order.
                continue
            visited_names.add(key)
            description = str(meta.get("description") or "").strip()
            sections = _parse_sections(body)
            usage = _parse_code_blocks(body)[:5]
            found.append(
                SkillInfo(
                    name=name,
                    description=description,
                    path=skill_md_path,
                    content=body.strip(),
                    metadata=meta,
                    sections=sections,
                    skill_type=_detect_skill_type(root),
                    usage_examples=usage,
                )
            )
    found.sort(key=lambda s: s.name.lower())
    return found
