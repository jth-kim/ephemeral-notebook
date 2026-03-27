# ephemeral-notebook

A terminal-native, notebook-like Python scratchpad that lives inside a tmux popup.

Write exploratory Python the way you would in Jupyter, but without leaving your terminal. ephemeral-notebook gives you a lightweight notebook UI with cells, execution, and output — all inside a tmux popup that floats over your current work and preserves state between opens.

## Features

- **tmux popup integration** — opens as a floating overlay, dismisses with `Ctrl+Q`, and picks up where you left off
- **Real IPython kernel** — full Python execution with the same kernel kept alive across popup sessions
- **Vim-style navigation** — `j`/`k`/`g`/`G` in nav mode, `Enter` to edit, `Escape` to return
- **Cell operations** — insert (`a`/`b`), delete (`dd`), undo (`z`), convert between Python and Markdown (`y`/`m`)
- **Run controls** — run cell (`Shift+Enter`), run all (`rr`), run above (`ra`), run below (`rb`)
- **Tab completion** — kernel-powered completions with builtin fallback
- **Smart editing** — auto-indent after `:`, bracket pairing, syntax highlighting
- **DataFrame rendering** — pandas DataFrames and Series display as formatted terminal tables
- **Clipboard support** — copy cell source (`cc`) or output (`co`) to system clipboard
- **Per-project sessions** — each project root gets its own notebook and kernel
- **Per-project startup** — configure auto-imports and startup code in `pyproject.toml`
- **Configurable** — popup size, theme, output limits, and more via `~/.config/ephemeral-notebook/config.toml`

## Requirements

- Python 3.11+
- tmux (for popup mode; works without tmux as a standalone TUI)

## Installation

```bash
pip install ephemeral-notebook
```

Or install from source:

```bash
git clone https://github.com/jonathankim/ephemeral-notebook.git
cd ephemeral-notebook
pip install -e .
```

## Quick start

From any tmux session:

```bash
ephemeral-notebook open
```

This opens a floating popup with a blank Python cell. Start typing, hit `Shift+Enter` to run, and `Ctrl+Q` to dismiss. Reopen with the same command — your cells and kernel are still there.

Without tmux, the notebook runs as a full-screen TUI:

```bash
ephemeral-notebook open --cwd /path/to/project
```

## Keybindings

### Nav mode (default)

| Key | Action |
|-----|--------|
| `Enter` | Enter edit mode on current cell |
| `a` / `b` | Insert cell above / below |
| `dd` | Delete current cell |
| `z` | Undo last delete |
| `y` / `m` | Convert cell to Python / Markdown |
| `Shift+Enter`, `R` | Run cell and move to next |
| `Ctrl+R` | Run cell and stay |
| `rr` | Run all cells |
| `ra` / `rb` | Run all above / below |
| `o` | Toggle output expand/collapse |
| `xx` | Clear current cell output |
| `cc` / `co` | Copy cell source / output |
| `l` | Toggle line numbers |
| `ii` | Interrupt kernel |
| `00` | Restart kernel |
| `dx` | Hard reset (clear all + restart) |
| `Up` / `Down`, `j` / `k` | Move between cells |
| `gg` / `G` | Jump to first / last cell |
| `Ctrl+U` / `Ctrl+D` | Page up / down |
| `Ctrl+Q`, `q` | Close popup (session stays alive) |

### Edit mode

| Key | Action |
|-----|--------|
| `Escape` | Return to nav mode |
| `Shift+Enter` | Run cell and move to next |
| `Ctrl+R` | Run cell and stay |
| `Tab` | Complete or indent |
| `Up` / `Down` | Move cursor; at boundary, move to adjacent cell |

## CLI commands

```
ephemeral-notebook open          # Open the notebook UI
ephemeral-notebook status        # Show project, interpreter, kernel, and session info
ephemeral-notebook reset         # Restart the kernel (keep cells)
ephemeral-notebook hard-reset    # Clear all cells and restart kernel
ephemeral-notebook kill          # Destroy the session entirely
```

## Configuration

### Global config

Optional settings at `~/.config/ephemeral-notebook/config.toml` (or `$XDG_CONFIG_HOME/ephemeral-notebook/config.toml`):

```toml
[popup]
width = "92%"
height = "92%"
x = "C"
y = "C"

[ui]
show_footer = true
status_verbosity = "minimal"   # "minimal" or "full"
markdown_center = false
output_max_lines = 12
code_theme = "monokai"
```

### Per-project startup

Add to your project's `pyproject.toml`:

```toml
[tool.ephemeral-notebook]
startup_imports = ["numpy as np", "pandas as pd"]
startup = ["from pathlib import Path"]
```

`startup_imports` expands to `import ...` statements. `startup` accepts arbitrary Python lines. Both run once when the kernel bootstraps.

## How it works

ephemeral-notebook resolves your project root (via `pyproject.toml` or `.git`) and Python interpreter (project `.venv`, ancestor `.venv`, or system `python3`). It starts an IPython kernel as a background process and persists session state to `~/.local/state/ephemeral-notebook/`. The kernel survives popup close/reopen — only `kill` or `hard-reset` stops it.

The TUI is built with [Textual](https://github.com/Textualize/textual) and communicates with the kernel via Jupyter's messaging protocol. Output rendering uses [Rich](https://github.com/Textualize/rich).

## Development

```bash
git clone https://github.com/jonathankim/ephemeral-notebook.git
cd ephemeral-notebook
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## License

MIT
