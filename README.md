# FastFold PyMOL Agent

FastFold-branded natural-language control for PyMOL.

## Install

```bash
conda activate pymol
pip install git+https://github.com/fastfold-ai/fastfold-pymol-agent.git
```

Add to `~/.pymolrc`:

```python
import fastfold_pymol_agent
fastfold_pymol_agent.__init_plugin__()
```

Then start PyMOL and run:

```text
fastfold help
```

## Command model

Use one command namespace:

```text
fastfold <prompt>
ff <prompt>
```

Core commands:

```text
fastfold <prompt>                    ask LLM and execute in PyMOL
fastfold dry <prompt>                generate commands, do not execute
fastfold save [file.py] <prompt>     execute and save generated script
fastfold save [file.py]              save last generated script
fastfold undo                        restore scene before last command
fastfold reset                       clear session and undo state
```

Setup/config commands:

```text
fastfold setup lmstudio
fastfold setup openai <key>
fastfold setup anthropic <key>
fastfold setup fastfold <key>

fastfold config show
fastfold config set <key> <value>
```

Session/log commands:

```text
fastfold log show
fastfold log save [session.py]
fastfold log export [session.json]
```

## Skills

Skill discovery commands:

```text
fastfold skills list
fastfold skills show <name>
fastfold skills howto <name>
fastfold skills search <query>
fastfold skills reload
```

Default config file:

```text
~/.fastfold-pymol-agent.json
```

Default local skills path:

```text
~/.fastfold-pymol-agent/skills
```

Minimal skill folder:

```text
~/.fastfold-pymol-agent/skills/protein-coloring/SKILL.md
```

Optional skill files:

- `skill.json` for executor metadata
- `scripts/` for helper scripts
- `references/` for longer docs/schemas

After adding/editing skills, run:

```text
fastfold skills reload
```

## Notes

- Import package is `fastfold_pymol_agent`.
- Root command is `fastfold` (with `ff` alias).
- Legacy `pm*` commands are intentionally not part of this interface.
# See README_NEW.md for current documentation.
# FastFold PyMOL Agent

Use `fastfold` from PyMOL.
# FastFold PyMOL Agent

Natural-language control for PyMOL with FastFold-branded commands and drop-in skill discovery.

## Install

```bash
conda activate pymol
pip install git+https://github.com/fastfold-ai/fastfold-pymol-agent.git
```

Add to `~/.pymolrc`:

```python
import fastfold_pymol_agent
fastfold_pymol_agent.__init_plugin__()
```

## Main commands

```text
fastfold <prompt>
fastfold dry <prompt>
fastfold save [file.py] <prompt>
fastfold save [file.py]
fastfold undo
fastfold reset
ff <...>
```

## Setup

```text
fastfold setup lmstudio
fastfold setup openai <key>
fastfold setup anthropic <key>
fastfold setup fastfold <key>
fastfold config show
fastfold config set <key> <value>
```

Config path:

```text
~/.fastfold-pymol-agent.json
```

## Skills

```text
fastfold skills list
fastfold skills show <name>
fastfold skills howto <name>
fastfold skills search <query>
fastfold skills reload
```

Default skill directory:

```text
~/.fastfold-pymol-agent/skills
```

Minimal skill example:

```text
~/.fastfold-pymol-agent/skills/protein-coloring/SKILL.md
```

## Session logs

```text
fastfold log show
fastfold log save [session.py]
fastfold log export [session.json]
```

## Notes

- Import package: `fastfold_pymol_agent`
- Root command: `fastfold` (alias `ff`)
- Legacy `pm*` commands are not part of this interface.
# FastFold PyMOL Agent

A PyMOL plugin that lets you control PyMOL with natural language using a FastFold-branded command surface and skill discovery.

```text
PyMOL> fastfold fetch 1hpv and show as cartoon colored by chain
PyMOL> fastfold dry render a publication quality PNG with white background
PyMOL> fastfold skills list
```

## Features

- Natural language to executable PyMOL code.
- Multi-turn conversation memory per session.
- LLM backends: LM Studio, OpenAI, Anthropic.
- FastFold key setup for skill-backed workflow integrations.
- Auto-discovered skills from `skills_paths`.
- Skill introspection commands (`list`, `show`, `howto`, `search`, `reload`).

## Requirements

- [PyMOL](https://pymol.org) (open-source)
- Python 3.8+
- One LLM backend:
  - [LM Studio](https://lmstudio.ai) (local, no cloud key required)
  - OpenAI API key
  - Anthropic API key

## Installation

Activate the same conda environment used by PyMOL, then install:

```bash
conda activate pymol
pip install git+https://github.com/fastfold-ai/fastfold-pymol-agent.git
```

## Load plugin in PyMOL

Add these lines to `~/.pymolrc`:

```python
import fastfold_pymol_agent
fastfold_pymol_agent.__init_plugin__()
```

Verify:

```text
PyMOL> fastfold help
```

## Quick start

```text
PyMOL> fastfold setup lmstudio
PyMOL> fastfold setup anthropic <your-api-key>
PyMOL> fastfold setup fastfold <your-api-key>
PyMOL> fastfold fetch 1hpv and color by chain
```

## Commands

### Prompt execution

```text
fastfold <prompt>                       ask LLM and execute
fastfold dry <prompt>                   generate code but do not execute
fastfold save [file.py] <prompt>        execute and save script
fastfold save [file.py]                 save last generated script
fastfold undo                           restore scene before last command
fastfold reset                          clear conversation and undo state
ff <...>                                alias for fastfold
```

### Setup and config

```text
fastfold setup lmstudio
fastfold setup openai <key>
fastfold setup anthropic <key>
fastfold setup fastfold <key>

fastfold config show
fastfold config set backend anthropic
fastfold config set anthropic_model claude-sonnet-4-6
fastfold config set output_dir ~/Desktop/figures
fastfold config set skills_paths ~/.fastfold-pymol-agent/skills,/path/to/skills
```

Config is stored at:

```text
~/.fastfold-pymol-agent.json
```

### Skills

```text
fastfold skills list
fastfold skills show fold
fastfold skills howto fold
fastfold skills search webhook
fastfold skills reload
```

### Session log

```text
fastfold log show
fastfold log save [session.py]
fastfold log export [session.json]
```

## Skill folders (drop-in model)

Skills are auto-discovered from configured `skills_paths`. By default:

```text
~/.fastfold-pymol-agent/skills
```

A skill folder requires `SKILL.md`:

```text
~/.fastfold-pymol-agent/skills/protein-coloring/SKILL.md
```

Optional files:

- `skill.json` for executor metadata (`script`, `http_workflow`, etc.)
- `scripts/` for executable helpers
- `references/` for long docs/schemas

After adding or editing skills:

```text
fastfold skills reload
```

## Example prompts

```text
fastfold fetch 1hpv and display it as cartoon colored by chain
fastfold what residues are within 4 angstroms of the ligand?
fastfold export a CSV of CA b-factors
fastfold dry align 1hpv to 3rze and color RMSD by spectrum
```

## Notes

- Import package: `fastfold_pymol_agent`
- Root command: `fastfold` (alias `ff`)
- Legacy `pm*` commands are not part of this interface.
# FastFold PyMOL Agent

A PyMOL plugin that lets you control PyMOL with natural language using a FastFold-branded command surface and skill discovery.

```text
PyMOL> fastfold fetch 1hpv and show as cartoon colored by chain
PyMOL> fastfold dry render a publication quality PNG with white background
PyMOL> fastfold skills list
```

## Features

- Natural language to executable PyMOL code.
- Multi-turn conversation memory per session.
- LLM backends: LM Studio, OpenAI, Anthropic.
- FastFold key setup for skill-backed workflow integrations.
- Auto-discovered skills from `skills_paths`.
- Skill introspection commands (`list`, `show`, `howto`, `search`, `reload`).

## Requirements

- [PyMOL](https://pymol.org) (open-source)
- Python 3.8+
- One LLM backend:
  - [LM Studio](https://lmstudio.ai) (local, no cloud key required)
  - OpenAI API key
  - Anthropic API key

## Installation

Activate the same conda environment used by PyMOL, then install:

```bash
conda activate pymol
pip install git+https://github.com/fastfold-ai/fastfold-pymol-agent.git
```

## Load plugin in PyMOL

Add these lines to `~/.pymolrc`:

```python
import fastfold_pymol_agent
fastfold_pymol_agent.__init_plugin__()
```

Verify:

```text
PyMOL> fastfold help
```

## Quick start

### LM Studio

```text
PyMOL> fastfold setup lmstudio
PyMOL> fastfold fetch 1hpv and color by chain
```

### OpenAI

```text
PyMOL> fastfold setup openai <your-api-key>
```

### Anthropic

```text
PyMOL> fastfold setup anthropic <your-api-key>
```

### FastFold skills key

```text
PyMOL> fastfold setup fastfold <your-api-key>
```

## Commands

### Prompt execution

```text
fastfold <prompt>                       ask LLM and execute
fastfold dry <prompt>                   generate code but do not execute
fastfold save [file.py] <prompt>        execute and save script
fastfold save [file.py]                 save last generated script
fastfold undo                           restore scene before last command
fastfold reset                          clear conversation and undo state
ff <...>                                alias for fastfold
```

### Setup and config

```text
fastfold setup lmstudio
fastfold setup openai <key>
fastfold setup anthropic <key>
fastfold setup fastfold <key>

fastfold config show
fastfold config set backend anthropic
fastfold config set anthropic_model claude-sonnet-4-6
fastfold config set output_dir ~/Desktop/figures
fastfold config set skills_paths ~/.fastfold-pymol-agent/skills,/path/to/skills
```

Config is stored at:

```text
~/.fastfold-pymol-agent.json
```

### Skills

```text
fastfold skills list
fastfold skills show fold
fastfold skills howto fold
fastfold skills search webhook
fastfold skills reload
```

### Session log

```text
fastfold log show
fastfold log save [session.py]
fastfold log export [session.json]
```

## Skill folders (drop-in model)

Skills are auto-discovered from configured `skills_paths`. By default:

```text
~/.fastfold-pymol-agent/skills
```

A skill folder requires `SKILL.md`:

```text
~/.fastfold-pymol-agent/skills/protein-coloring/SKILL.md
```

Optional files:

- `skill.json` for executor metadata (`script`, `http_workflow`, etc.)
- `scripts/` for executable helpers
- `references/` for long docs/schemas

After adding or editing skills:

```text
fastfold skills reload
```

## Example prompts

```text
fastfold fetch 1hpv and display it as cartoon colored by chain
fastfold what residues are within 4 angstroms of the ligand?
fastfold export a CSV of CA b-factors
fastfold dry align 1hpv to 3rze and color RMSD by spectrum
```

## Notes

- This project uses a hard rebrand and command reset:
  - import: `fastfold_pymol_agent`
  - root command: `fastfold`
- Legacy `pm*` commands are not part of the new interface.
# PromptMOL

![PromptMol demo](demo.gif)

A PyMOL plugin that lets you control PyMOL with natural language. Type plain language prompts directly in the PyMOL command line and have an LLM translate them into PyMOL commands that execute automatically.

```
PyMOL> pm fetch 1hpv and show as cartoon colored by chain
PyMOL> pm make the ligand yellow sticks with a transparent surface
PyMOL> pm render a publication quality PNG with a white background
```

And other commands with increasing complexity...

```
PyMOL> pm what residues are within 4 angstroms of the ligand?
PyMOL> pm measure the distance between residue 50 CA and residue 100 CA
PyMOL> pm calculate the molecular weight of the protein
PyMOL> pm export a CSV containing the B-factors 
```

Supports [LM Studio](https://lmstudio.ai) (local, no API key needed), OpenAI, and Anthropic, switchable at any time with a single command.

---

## Features

- **Natural language → PyMOL commands** - describe what you want, PromptMOL generates and executes the API calls
- **Multi-turn conversation** - the LLM remembers prior context within a session, so follow-up commands just work
- **Three LLM backends** - LM Studio (local), OpenAI, Anthropic; switch with `pmcfg set backend`
- **Dry-run mode** - preview generated commands before executing with `--dry`
- **Script saving** - save any generated script as a standalone `.py` file with `--save` or `pmsave`
- **Session log** - save the full session as a replayable annotated script with `pmlog save`
- **Output directory** - route all saved files (PNGs, CSVs, etc.) to a folder with `--outdir` or `pmcfg set output_dir`

---

## Requirements

- [PyMOL](https://pymol.org) (open-source) - tested with open-source PyMOL via conda
- Python 3.8+
- One of:
  - [LM Studio](https://lmstudio.ai) running locally (recommended for getting started, no API key needed)
  - An OpenAI API key
  - An Anthropic API key

---

## Installation

### 1. Install PromptMol

Activate the same conda environment that PyMOL uses, then install directly from GitHub:

```bash
conda activate pymol
pip install git+https://github.com/KodyKlupt/PromptMOL.git
```

This installs PromptMol and its dependencies (`openai`, `anthropic`) in one step.

To update to the latest version later:

```bash
pip install --upgrade git+https://github.com/KodyKlupt/PromptMOL.git
```

### 2. Load the plugin in PyMOL

Add these two lines to `~/.pymolrc` (create the file if it doesn't exist):

```python
import promptmol
promptmol.__init_plugin__()
```

PyMOL will load PromptMol automatically every time it starts. To verify it worked, open PyMOL and type:

```
pm help
```

---

## Quick Start

### Using LM Studio (local, no API key)

1. Download and open [LM Studio](https://lmstudio.ai) 
2. Load any chat model
3. Start the local server (default port: 1234)
4. Open PyMOL and PromptMol defaults to LM Studio, no configuration needed

```
PyMOL> pm fetch 1hpv
PyMOL> pm show it as cartoon colored by secondary structure
PyMOL> pm make the ligand sticks with yellow carbons
```

### Using OpenAI or Anthropic

```
PyMOL> pmcfg set backend openai
PyMOL> pmcfg set api_key sk-...

PyMOL> pmcfg set backend anthropic
PyMOL> pmcfg set api_key sk-ant-...
```

---

## Examples

**Visualization & Styling**
```
pm fetch 1hpv and display it as a cartoon colored by chain
pm show the ligand as yellow sticks and add a transparent grey surface to the protein
pm make the protein slate blue and color residues 50-60 red
```

**Structural Analysis**
```
pm what residues are within 4 angstroms of the ligand?
pm measure the distance between residue 50 CA and residue 100 CA
pm calculate the molecular weight of the protein
```

**Exporting & Rendering**
```
pm render a 300dpi publication quality PNG with a white background
pm save the current structure as a PDB file in my downloads folder
pm export a CSV containing the B-factors for all alpha carbons
```

---

## Command Reference

### `pm` - main command

```
pm <prompt>
pm --dry <prompt>                    preview commands without executing
pm --save <prompt>                   execute and save script (auto-named)
pm --save filename.py <prompt>       execute and save to filename.py
pm --outdir /path <prompt>           set output folder for this command
pm --model <name> <prompt>           override LLM model for this one command
pm --dry --save --outdir /p <prompt> combine flags freely
pm help                              show usage
```

If generated code raises an error, PromptMol automatically sends the error
back to the LLM and retries once.

### `pmundo` - undo last command

```
pmundo                               restore scene to before the last pm command
```

The scene state is snapshotted automatically before each execution.

### `pmcfg` - configuration

```
pmcfg show                           print current config
pmcfg set backend lmstudio           use LM Studio (default)
pmcfg set backend openai             use OpenAI
pmcfg set backend anthropic          use Anthropic
pmcfg set api_key <key>              set API key (OpenAI or Anthropic)
pmcfg set model <name>               set LM Studio model name
pmcfg set openai_model gpt-4o        set OpenAI model
pmcfg set anthropic_model claude-sonnet-4-6
pmcfg set base_url http://localhost:1234/v1   LM Studio server URL
pmcfg set output_dir ~/my/figures    persistent output folder
pmcfg set max_history 20             number of conversation turns to keep
```

Config is saved to `~/.promptmol.json`.

### `pmreset` - clear session

```
pmreset                              clear conversation history, log, and undo state
```

### `pmsave` - save last script

```
pmsave                               save last generated script (auto-named)
pmsave filename.py                   save with a specific name
```

### `pmlog` - session log

```
pmlog show                           print full session log to console
pmlog save                           save session as annotated .py script (auto-named)
pmlog save session.py                save with a specific name
pmlog export                         export session as JSON (auto-named)
pmlog export session.json            export with a specific name
```

The session log is a valid Python script with each step labeled by timestamp
and prompt, so it can be replayed directly in PyMOL. The JSON export is useful
for programmatic analysis or sharing structured session data.

---

## Output Directory

Any files generated by LLM scripts (PNGs, CSVs, exported PDBs, etc.) respect the active output directory:

```
# Per-command
pm --outdir ~/Desktop/figures render a 300dpi PNG

# Persistent (survives restarts)
pmcfg set output_dir ~/Desktop/figures
```

Scripts saved by `--save`, `pmsave`, and `pmlog save` also land in this directory. Defaults to the current working directory if not set.

---

## Tips

- **Give context**: `pm the ligand is called LIG - show it as sticks` works better than assuming the LLM knows your structure
- **Follow-up naturally**: after loading a structure, subsequent commands can reference it without reloading
- **Use `--dry` first** for complex requests to review commands before they run
- **Replay sessions**: `pmlog save` produces a standalone script you can share or re-run

---

## Citation

@misc{PromptMOL,
    author={Kody A. Klupt},
    title={PromptMOL: Controlling PyMOL with Natural Language},
    year={2026},
    url={https://github.com/KodyKlupt/PromptMOL},

---

## Use of AI

This project was developed with the assistance of Claude Code.
