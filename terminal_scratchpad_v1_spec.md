# Terminal Scratchpad v1 Spec

## Summary

Terminal Scratchpad is a terminal-native, notebook-like scratch tool for Python work. It is designed to be fast, visually clear, ephemeral by default, and separate from real package development.

The tool is launched from tmux as a popup, attaches to a single background scratch session for the current project, and hides cleanly when dismissed. It keeps temporary exploratory state available during the working session without making notebook files part of the normal workflow.

## Product goals

- Feel close enough to Jupyter that it is pleasant for exploratory work
- Stay terminal-first and popup-friendly inside tmux
- Keep scratch work clearly separate from `src/` and `tests/`
- Preserve session state when the popup closes
- Avoid durable notebook artifacts in normal use
- Follow the active project's Python environment automatically
- Be simple enough to use as a daily scratchpad, not a second development environment

## Product non-goals

- Replacing Jupyter for full notebook authoring or publishing
- Making notebooks a first-class project artifact
- Supporting collaborative or multi-user notebooks
- Supporting multiple live attachments to the same scratch session
- Solving multi-popup workspace management in v1
- Prioritizing plots or rich media rendering in v1

## Core UX model

The user opens a tmux popup from anywhere inside a project. The tool resolves the current project and either attaches to that project's existing scratch session or starts a new one.

The UI presents a notebook-like TUI:

- ordered cells
- Python code cells
- markdown cells
- inline outputs below cells
- clear visual separation between code, markdown, and output
- scrollable notebook history
- keyboard-first interaction

Closing the popup with `q` hides the UI but does not destroy the session. Reopening the popup returns the user to the same in-memory scratch notebook.

## Session model

### Session identity

- v1 exposes one scratch session per project
- internally, sessions should still be keyed by a session ID so the implementation can grow later without a rewrite

### Project identity

Project root is resolved as:

1. nearest ancestor containing `pyproject.toml`
2. else nearest ancestor containing `.git`
3. else current working directory

This root is used for:

- session scoping
- Python resolution
- status display in the UI
- future per-project config

### Attachment rules

- only one active UI attachment per project session
- if the user attempts to open the same session twice, the second attach is blocked with a clear message

### Session lifetime

- sessions persist after popup close
- sessions do not need to survive a full app restart or tmux restart in v1
- explicit `kill` destroys the session

## Persistence model

The tool is ephemeral from the user's perspective, but it may keep app-managed transient state while the session is alive.

Rules:

- no notebook files are written into the project by default
- scratch state should not be stored in the repo
- any temporary state should live in app-managed state outside the project
- v1 should not provide an easy export-to-notebook workflow

Rationale:

- avoids repo pollution
- avoids accidental commits
- preserves a clean distinction between scratch work and real development

## Python environment resolution

When the tool is launched, it resolves Python for the current project root using:

1. `<project-root>/.venv/bin/python`
2. nearest ancestor `.venv/bin/python` if different from the root lookup
3. system `python3`

Notes:

- this aligns with common `uv` and local virtualenv workflows
- the tool should display the resolved interpreter and project root clearly in the UI
- if the fallback is system Python, that is acceptable and should be obvious in the status area

## UI requirements

### Visual structure

- code cells rendered in a visually distinct boxed section
- markdown cells visually distinct from code cells
- outputs rendered in a separate area below the producing cell
- current cell focus should be obvious
- status bar should show:
  - project root name or path
  - interpreter path or label
  - session status

### Output behavior

- outputs are shown inline
- long outputs are truncated by default
- truncated outputs can be expanded on demand
- outputs are scrollable
- text rendering is the priority for v1
- tables and colorized output are desirable if straightforward
- plot rendering is out of scope for v1

### Editing model

- cell editing happens inline inside the TUI
- the user does not drop out to `$EDITOR` for normal editing
- terminal-realistic keybindings should be preferred over GUI-specific assumptions

## Cell model

Supported cell types in v1:

- Python
- Markdown

Default new notebook state:

- one empty Python cell

Desired interactions:

- insert cell above
- insert cell below
- switch current cell to markdown
- switch current cell to Python
- execute current cell
- execute current cell and move to next
- execute all cells
- navigate between cells
- expand/collapse long output

Markdown rendering:

- plain text rendering is acceptable for v1 if richer formatting is costly
- architecture should not block nicer markdown rendering later

## Command and behavior surface

### External commands

Minimum v1 command surface:

- `open`
- `reset`
- `hard-reset`
- `kill`
- `status`

Expected behavior:

- `open`: open the popup UI for the resolved project session
- `reset`: restart Python/kernel state but preserve notebook structure and cells
- `hard-reset`: clear notebook contents and outputs, then create one empty Python cell
- `kill`: destroy the project session entirely
- `status`: show whether a project session exists and which interpreter it uses

### In-app behavior

- `q`: detach/hide UI
- closing the popup never implies destroy
- kernel crash should preserve notebook structure and offer restart

## Keyboard model

The tool should preserve familiar notebook intent while remaining terminal-safe.

Preferred v1 bindings:

- `a`: insert cell above
- `b`: insert cell below
- `m`: set cell to markdown
- `y`: set cell to Python
- `Shift-Enter`: run current cell and move
- `Ctrl-Enter`: run current cell and stay
- `q`: hide/detach

Guidance:

- avoid relying on `Cmd` key behavior because terminal/tmux support is inconsistent
- preserve normal terminal editing behavior where possible
- support common text-editing motions if the chosen TUI stack allows it cleanly

## Bootstrap behavior

Sessions may optionally pre-import a minimal default set:

- `import numpy as np`
- `import pandas as pd`

This should be configurable in the future, likely via `pyproject.toml`.

v1 rule:

- minimal sensible defaults are acceptable
- no large implicit environment setup
- all additional imports remain explicit

## Future config

Future per-project configuration should be supported through `pyproject.toml`, for example a tool section for:

- default imports
- UI preferences
- popup placement defaults

This config is not required for v1, but the architecture should leave room for it.

## Popup behavior

v1 should support configurable popup geometry and placement.

Requirements:

- centered popup is the default
- placement and size must not be hard-coded into the application model
- the implementation should allow later support for alternative placements without architectural changes

Clarification:

- multi-popup orchestration is not part of this project in v1
- the tool only needs to avoid assuming "single centered popup forever"

## Recommended architecture

v1 should use three logical parts:

1. launcher
2. session manager
3. TUI client

### Launcher

Responsibilities:

- detect current cwd
- resolve project root
- resolve Python interpreter
- open tmux popup with the TUI client

### Session manager

Responsibilities:

- maintain one live scratch session per project
- own notebook state and kernel lifecycle
- enforce single active attachment
- serve notebook state to the UI

### TUI client

Responsibilities:

- render notebook cells and output
- handle editing and navigation
- send execution and notebook actions to the session manager
- detach cleanly without destroying session state

## Acceptance criteria

- One command or keybinding opens the scratchpad popup for the current project
- Closing or quitting the popup hides the UI without losing the current scratch session state
- One command resets Python state while preserving notebook structure
- One command performs a full hard reset to a blank notebook with one empty Python cell
- One command fully kills the scratch session
- Cells support both Python and markdown modes
- Outputs are inline, scrollable, and truncated with expand-on-demand
- Keyboard-first interaction is strong and terminal-safe
- No notebook files or scratch artifacts are saved into the project by default
- Python environment selection follows the current project's local environment automatically
- The UI clearly shows the active project and interpreter
- The tool remains clearly separate from real package code and tests
- Popup placement is configurable and not hard-coded as a permanent architectural assumption
- Kernel crash does not destroy notebook structure and can be recovered with restart

## v1 implementation priorities

1. Session lifecycle and project/Python resolution
2. Popup launch and reattach behavior
3. Notebook TUI with Python and markdown cells
4. Cell execution and inline output rendering
5. Reset, hard-reset, kill, and crash recovery
6. Output truncation and expansion
7. Minimal default imports and status display

## Open questions deferred beyond v1

- richer markdown rendering
- mouse interaction
- table-specific rendering improvements
- plots and image output
- multiple named sessions per project
- multi-popup workspace coordination
- explicit export features
