# Terminal Scratchpad Implementation Plan

## Goal

Build a v1 terminal-native Python scratchpad that behaves like an ephemeral notebook inside a tmux popup.

## Recommended build order

1. Bootstrap the project
2. Implement project and Python resolution
3. Implement session lifecycle
4. Build the notebook TUI shell
5. Add cell execution and output rendering
6. Add reset and recovery behaviors
7. Add tmux popup integration
8. Polish usability and visuals

## Phase 1: Project bootstrap

- Choose implementation language and package structure
- Set up packaging, linting, formatting, and tests
- Define the CLI surface:
  - `open`
  - `reset`
  - `hard-reset`
  - `kill`
  - `status`

## Phase 2: Project and interpreter resolution

Implement deterministic resolution for:

- project root:
  - nearest `pyproject.toml`
  - else nearest `.git`
  - else cwd
- Python interpreter:
  - `<project-root>/.venv/bin/python`
  - else nearest ancestor `.venv/bin/python`
  - else system `python3`

Deliverables:

- unit-tested resolution logic
- status output showing resolved project and interpreter

## Phase 3: Session manager

Implement a background session manager that:

- owns one session per project root
- preserves notebook state while detached
- enforces one active attachment at a time
- supports:
  - create or attach
  - reset kernel
  - hard reset notebook
  - kill session
  - recover from kernel crash

Deliverables:

- session registry
- session lifecycle tests
- crash/restart behavior

## Phase 4: Notebook TUI shell

Build the basic notebook interface with:

- scrollable cell list
- visible focus state
- code cells
- markdown cells
- inline output areas
- status bar showing project and interpreter

Keybindings for first pass:

- `a`
- `b`
- `m`
- `y`
- `Shift-Enter`
- `Ctrl-Enter`
- `q`

Deliverables:

- notebook rendering
- inline editing
- cell insertion and navigation

## Phase 5: Execution and outputs

Add Python execution through the session kernel:

- run current cell and stay
- run current cell and move
- run all cells
- capture stdout/stderr/result
- render outputs below cells
- truncate large outputs with expand-on-demand

Deliverables:

- execution pipeline
- output rendering
- large-output handling

## Phase 6: Reset and recovery

Implement behavior exactly as specified:

- `reset`: restart kernel, keep notebook structure
- `hard-reset`: clear cells and outputs, create one empty Python cell
- kernel crash: preserve notebook structure and offer restart

Deliverables:

- command handling
- crash-state UI
- tests for reset semantics

## Phase 7: tmux integration

Add tmux-facing entry points for popup use:

- open popup from current cwd
- configurable popup size and placement
- detach cleanly on `q`
- reopen into same live session

Deliverables:

- launcher command
- tmux popup invocation
- geometry configuration support

## Phase 8: UX polish

Improve the notebook feel without widening scope:

- better visual separation of code and output
- syntax highlighting
- improved markdown rendering if cheap
- clearer status and error messaging
- optional default imports:
  - `numpy as np`
  - `pandas as pd`

## Suggested technical decisions

- Use Python for the application itself
- Keep state outside the project directory
- Use `pyproject.toml` later for project-specific config
- Treat multi-popup orchestration as out of scope for v1

## Testing priorities

- project root resolution
- interpreter resolution
- one-session-per-project enforcement
- detach vs kill behavior
- reset vs hard-reset behavior
- kernel crash recovery
- output truncation behavior

## Definition of done for v1

- A tmux popup opens the scratchpad for the current project
- Closing the popup does not lose the active session
- The UI supports Python and markdown cells
- Inline outputs are visible and scrollable
- Large outputs truncate and expand
- Reset, hard-reset, kill, and status all work
- The active interpreter is clearly shown
- No notebook files are written into the project by default
