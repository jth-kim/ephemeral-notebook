# popup-notebook

Terminal-native, notebook-like Python scratchpad for tmux workflows.

## Status

This repository currently contains:

- product brief
- v1 spec
- implementation plan
- initial Python project scaffold

## Intended stack

- Python
- Textual
- Rich
- Typer
- jupyter_client
- ipykernel
- uv

## Planned CLI

- `popup-notebook open`
- `popup-notebook reset`
- `popup-notebook hard-reset`
- `popup-notebook kill`
- `popup-notebook status`

## Development

This scaffold is intentionally light. The first implemented behavior is project root and Python interpreter resolution.

## Global Config

Optional global settings live at `~/.config/popup-notebook/config.toml` or under `XDG_CONFIG_HOME`.

Example:

```toml
[popup]
width = "80%"
height = "80%"
x = "C"
y = "C"

[ui]
show_footer = true
status_verbosity = "minimal"
markdown_center = false
output_max_lines = 12
code_theme = "monokai"
```
