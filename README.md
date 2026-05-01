# Fastfold PyMOL Agent

Fastfold PyMOL Agent is a PyMOL plugin for biology workflows: run Fastfold skills, bring generated artifacts into PyMOL, and keep iterating with natural-language visualization and analysis.

- Python import: `fastfold_pymol_agent`
- Main command: `fastfold` (alias: `ff`)
- Conversational command: `agent <message>`
- Multiline GUI chat: `fastfold ui`
- Agent repository: `https://github.com/fastfold-ai/fastfold-pymol-agent.git`
- Official skills pack: `https://github.com/fastfold-ai/skills/tree/main/skills`

---

## Requirements

- [PyMOL (open-source)](https://github.com/schrodinger/pymol-open-source) — tested with open-source PyMOL via conda (for example `conda-forge` package: [pymol-open-source](https://anaconda.org/conda-forge/pymol-open-source))

---

## Quick Install

Works on macOS and Linux (auto-detects platform):

Full install (installs PyMOL + agent):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/fastfold-ai/fastfold-pymol-agent/main/scripts/install.sh)
```

Agent-only quick install (assumes PyMOL is already installed in env `pymol`):

If PyMOL is not installed yet, follow the official open-source install guide: [schrodinger/pymol-open-source INSTALL](https://github.com/schrodinger/pymol-open-source/blob/master/INSTALL)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/fastfold-ai/fastfold-pymol-agent/main/scripts/install.sh) -- --agent-only
```

Agent-only with custom conda env name:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/fastfold-ai/fastfold-pymol-agent/main/scripts/install.sh) -- --agent-only --env-name myenv
```

Optional safer flow (download, inspect, run):

```bash
curl -fsSL https://raw.githubusercontent.com/fastfold-ai/fastfold-pymol-agent/main/scripts/install.sh -o /tmp/fastfold_pymol_install.sh
less /tmp/fastfold_pymol_install.sh
bash /tmp/fastfold_pymol_install.sh
```

This script will:

1. Create/use conda env `pymol` (override with `--env-name <env>`)
2. Install `fastfold-pymol-agent` (local editable install if available, otherwise from GitHub)
3. Optionally install PyMOL build dependencies + PyMOL source (full mode)
4. Update `~/.pymolrc` to auto-load `fastfold_pymol_agent`
5. Fetch skills from `fastfold-ai/skills` and copy to `~/.fastfold-pymol-agent/skills`

Then launch PyMOL:

```bash
conda activate pymol
pymol
```

This opens the PyMOL UI. Then follow the **First run in PyMOL** section below to configure API keys and launch the agent UI.

```text
fastfold help
```

---

## First run in PyMOL

Configure keys and start the agent:

```text
fastfold doctor
fastfold setup <your-anthropic-api-key> <your-fastfold-api-key>
fastfold ui
```

Where to get keys:

- Fastfold API key: [https://cloud.fastfold.ai/api-keys](https://cloud.fastfold.ai/api-keys)
- Anthropic API key: [https://platform.claude.com/dashboard](https://platform.claude.com/dashboard)

Or set keys individually:

```text
fastfold setup anthropic <your-anthropic-api-key>
fastfold setup fastfold <your-fastfold-api-key>
```

---

## Chat UI workflow (recommended)

Use the chat window for long prompts, local file paths, and multi-step workflows:

```text
fastfold ui
```

### Referencing local files in chat

- Use the **Insert File Path** button in the UI to inject absolute paths.
- You can also paste paths manually; keep paths quoted if they contain spaces.
- Ask explicitly what to do with each file (load, align, style, measure, export).

Examples:

```text
Load "/Users/you/data/model.cif" as object "pred_cif", show cartoon, color by chain, and center view.
```

```text
Load "/Users/you/data/model.pdb" as "ref_pdb", align it to "pred_cif", then highlight residues 45-70 as sticks.
```

```text
Load topology "/Users/you/data/protein.pdb" as "traj_top", load trajectory "/Users/you/data/run.dcd", then show RMSD over time and display frame 1 and last frame as cartoons.
```

### Combining Fastfold skills + PyMOL edits

Use one request that asks the agent to run a skill workflow and then style/analyze results in PyMOL.

Simple prompt example:

```text
Use esm1b in Fastfold to run a fold job.

Use these sequences:
Sequence 1 (protein): MGLSDGEWQLVLNVWGKVEADIPGHGQEVLIRLFKGHPETLERFDKFKHLKSEDEMKASEDLKKHGATVLTALGGILKKKGHHEAEIKPLAQSHATKHKIPVKYLEFISECIIQVLQSKHPGDFGADAQRAMNKALELFRKDMASNYKELGFQG and show the prediction as cartoon colored by secondary structure.
```

Example (fold -> CIF -> PyMOL):

```text
Use the fold skill to submit an esm1b job for this sequence, wait for completion, download the CIF, load it into PyMOL as "esm1b_result", then color by pLDDT and label low-confidence loops.
```

Example (MD workflow -> frames/artifacts -> PyMOL):

```text
Use md-openmmdl to run a short workflow from my topology and ligand files, fetch artifacts, load representative structures in PyMOL, then compare start vs end conformations with cartoons and sticks at the binding site.
```

Example (artifact refinement loop):

```text
From the latest Fastfold artifact, load structure(s), create publication-style scenes for chain interfaces, and export both a PNG and a PyMOL session file.
```

### PDB, CIF, and trajectory editing patterns

After files are loaded, ask for concrete modifications:

```text
PDB: show cartoon, color by chain, show ligand as sticks, and add hydrogen-bond distances.
CIF: map confidence to spectrum colors, select residues with confidence < 70, and make them transparent surface.
Trajectory: align all frames to chain A, compute RMSD, and generate snapshots for frames 1/50/100.
```

Tip: give object names in your prompt (`as "obj_name"`) so follow-up instructions are consistent.

---

## Commands

### Core

```text
fastfold <prompt>                     ask the agent and auto-execute
fastfold dry <prompt>                 preview generated commands
fastfold save [file.py] <prompt>      run prompt and save script
fastfold save [file.py]               save last generated script
fastfold undo                         restore scene before last command
fastfold reset                        clear conversation and undo state
ff <...>                              short alias for fastfold
```

### Agent mode and GUI

```text
agent <message>                       conversational alias
fastfold agent on|off|status          toggle/show agent mode
fastfold ui                           open multiline Fastfold Agent window
```

### Setup and config

```text
fastfold setup
fastfold setup <anthropic> <fastfold>
fastfold setup anthropic <key>
fastfold setup fastfold <key>
fastfold doctor

fastfold config show
fastfold config set <key> <value>
```

### Skills and logs

```text
fastfold skills list
fastfold skills show <name>
fastfold skills howto <name>
fastfold skills search <query>
fastfold skills reload

fastfold log show
fastfold log save [file.py]
fastfold log export [file.json]
```

---

## Skills (drop-in folders)

Default config file:

```text
~/.fastfold-pymol-agent.json
```

Default skills path:

```text
~/.fastfold-pymol-agent/skills
```

Minimum skill layout:

```text
~/.fastfold-pymol-agent/skills/my-skill/SKILL.md
```

Optional:

- `scripts/` for helper executables
- `references/` for docs/schemas
- `skill.json` for metadata

After adding/editing skills:

```text
fastfold skills reload
```

---

## Inspired by

- [KodyKlupt/PromptMOL](https://github.com/KodyKlupt/PromptMOL)
