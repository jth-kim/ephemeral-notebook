# Terminal Scratchpad Tool Brief

I want help designing and possibly implementing a terminal-native scratchpad tool for Python development. It should feel notebook-like in use, but remain intentionally ephemeral and non-authoritative.

## Context

- This idea came out of Python/time-series work, but the tool itself should be independent of any single project
- Shell: `zsh`
- I work in Vim + tmux
- I am comfortable in Vim and reasonably comfortable in tmux
- I have done a lot of coding in Jupyter notebooks because they make experimentation easy
- I am trying to shift toward a more rigorous package/test workflow for maintainable Python work
- I do not want notebooks to be the source of truth for package code
- I still want very fast exploratory feedback loops

## Current development philosophy

- Real code should live in `src/`
- Tests should live in `tests/`
- Scratch/exploration should be disposable
- I want to preserve the speed of exploratory work without letting notebook state or copy-paste drift pollute the codebase

## What I learned already

- Using `pytest` to define expected behavior first is useful
- REPL/IPython is good enough for quick experimentation
- For package code, tests should express behavior, not reimplement the function
- Scratch-padding is still valuable, especially for math-heavy or library-behavior-heavy tasks
- I do not want to abandon exploration, only separate it from the permanent code path

## What I want now

I want a terminal-native scratchpad tool that feels meaningfully notebook-like, but is intentionally disposable and non-authoritative.

## Ideal characteristics

- Opens quickly from tmux
- Opens as a popup over my current tmux workflow
- Persistent for the current working session
- Easy to hide/show/focus
- Popup position and size should be controllable rather than assumed to be fixed
- Easy to wipe/reset to a clean state
- Never encourages saved exploratory artifacts to become permanent source-of-truth
- Keeps notebook state in memory unless I explicitly export something
- Good enough for:
  - trying library calls
  - quick math experiments
  - inspecting pandas Series / NumPy arrays
  - checking outputs before writing tests
- Works well with data-heavy development, where I often want to inspect vectors, lag outputs, decompositions, etc.

## Interaction model I want

- Notebook-like cells rather than just a plain REPL prompt
- Separate visual treatment for code cells, markdown cells, and outputs
- Comfortable keyboard-driven flow similar to Jupyter
- The popup should not be architecturally tied to only one fixed position on screen
- It should be possible to support multiple popup-based tools in the future without redesigning the whole system
- Desirable commands/interactions:
  - `a` / `b` for inserting cells
  - `m` / `y` for markdown vs Python cell mode
  - execute current cell and show output inline
  - scroll through prior cells and outputs
  - optional mouse support for selecting/focusing cells and scrolling
- Text UI is fine; I do not need a browser UI
- I want it to feel polished enough that using it is pleasant, not like a thin wrapper around a shell prompt

## Strong preference

- I do NOT want a normal notebook workflow to be the main answer
- I want something terminal-first
- If a notebook-like tool is proposed, it should be intentionally disposable and not produce lasting scratch files by default

## What I have already tried

- `.venv/bin/ipython` inside tmux
- `tmux split-window -vf ".venv/bin/ipython"` works
- Other tmux popup key bindings work fine for me, so popup support itself is not the issue
- tmux version is `3.6a`
- I am inside a tmux session
- Plain IPython in a split is viable already, but I want something more refined and more notebook-like

## What I specifically imagine

- Some kind of persistent popup scratch session over the terminal
- Open it, workshop a little, close it, come back later, and still see the same scratch state
- Closing the popup should not destroy the session
- Popup placement should be configurable so the UI can live in different parts of the screen
- The design should leave room for running more than one popup tool at the same time in the future
- One command to wipe the scratch session clean
- One command to fully kill the scratch session
- No permanent notebook save behavior by default
- Something that strongly discourages “scratch code becoming real code”
- It is fine if the persistent state is maintained by a background process/session, as long as the content is ephemeral unless explicitly exported

## What I do NOT need

- A lecture about why notebooks are bad
- A suggestion to just keep using Jupyter as usual
- A big abstract tool survey with no concrete recommendation
- Anything that shifts the real code workflow out of `src/` and `tests/`

## Python environment requirement

- The Python interpreter should follow the project I launched the popup from
- In practice, if I open the scratchpad from inside a project, it should use that project's local environment
- I commonly have project-local `uv` environments / `.venv` directories
- I do not want to manually reselect the interpreter every time
- If the tool tracks separate scratch sessions, they should probably be scoped per project root / working directory

## What I want from you

1. Propose a concrete terminal-native scratchpad setup/tool design.
2. Explain the tradeoffs of the best 1-2 options only.
3. Recommend one setup as the default.
4. If implementation makes sense, help me implement it in small steps.
5. Keep the solution pragmatic and lightweight.

## Development background

- I care about scalable, maintainable engineering practices
- I am happy to use external libraries rather than reimplement standard stats machinery unless there is a reason
- I recently added small metrics using a test-first-ish workflow and that experience was good
- I want future experimentation to fit that same disciplined loop:
  - scratch
  - decide expected behavior
  - write test
  - implement in package
  - run pytest

## Final request

Please optimize for a workflow/tool that supports that loop well while still feeling enough like a notebook that I will actually want to use it.

## Acceptance criteria

- One command or keybinding opens the scratchpad popup for the current project
- Closing or quitting the popup hides the UI without losing the current scratch session state
- Popup placement is configurable and not hard-coded to a single default layout
- One command resets the scratchpad to a clean state
- One command fully kills the scratch session
- Cells support both Python and markdown modes
- Outputs are shown inline and are scrollable
- Keyboard-first interaction is excellent; mouse support is optional but desirable
- No notebook files or scratch artifacts are saved by default
- Python environment selection follows the current project's local environment automatically
- The tool remains clearly separate from real package code and tests
- The overall architecture does not assume this will always be the only popup-based tool
