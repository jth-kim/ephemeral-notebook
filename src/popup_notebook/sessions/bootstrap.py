from __future__ import annotations

import inspect
import json
import textwrap


BOOTSTRAP_VERSION = 1


class _PNRenderable:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return self.text

    def __str__(self):
        return self.text


def _pn_is_number(value):
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except Exception:
        return False
    return math.isfinite(number)


def _pn_clip(value, max_width=24):
    if value is None:
        text = ""
    else:
        text = str(value)
    text = text.replace("\r", "").replace("\n", " ↩ ")
    if len(text) > max_width:
        return text[: max_width - 1] + "…"
    return text


def _pn_align(text, width, right=False):
    text = str(text)
    if right:
        return text.rjust(width)
    return text.ljust(width)


def _pn_box_table(headers, rows, aligns, max_width=24):
    clipped_headers = [_pn_clip(header, max_width=max_width) for header in headers]
    clipped_rows = [
        [_pn_clip(value, max_width=max_width) for value in row]
        for row in rows
    ]
    widths = [len(header) for header in clipped_headers]
    for row in clipped_rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    top = "┌" + "┬".join("─" * (width + 2) for width in widths) + "┐"
    header = (
        "│ "
        + " │ ".join(
            _pn_align(value, widths[index], bool(aligns[index]))
            for index, value in enumerate(clipped_headers)
        )
        + " │"
    )
    divider = "├" + "┼".join("─" * (width + 2) for width in widths) + "┤"
    body = [
        "│ "
        + " │ ".join(
            _pn_align(value, widths[index], bool(aligns[index]))
            for index, value in enumerate(row)
        )
        + " │"
        for row in clipped_rows
    ]
    bottom = "└" + "┴".join("─" * (width + 2) for width in widths) + "┘"
    return "\n".join([top, header, divider, *body, bottom])


def _pn_format_dataframe(df, max_rows=20, max_cols=8, max_width=24):
    frame = df.iloc[:max_rows, :max_cols]
    headers = [df.index.name or "#"] + [str(column) for column in frame.columns]
    rows = [[index, *row.tolist()] for index, (_, row) in zip(range(len(frame)), frame.iterrows())]
    for display_index, row in enumerate(rows):
        row[0] = frame.index[display_index]

    if len(df.columns) > max_cols:
        headers.append("…")
        for row in rows:
            row.append("…")
    if len(df.index) > max_rows:
        rows.append(["…"] * len(headers))

    aligns = []
    for column_index in range(len(headers)):
        values = [
            row[column_index]
            for row in rows
            if column_index < len(row) and row[column_index] != "…"
        ]
        aligns.append(bool(values) and all(_pn_is_number(value) for value in values))

    return _pn_box_table(headers, rows, aligns, max_width=max_width)


def _pn_format_series(series, max_rows=20, max_width=24):
    column_name = series.name if series.name not in {None, ""} else "value"
    return _pn_format_dataframe(
        series.to_frame(name=column_name),
        max_rows=max_rows,
        max_cols=1,
        max_width=max_width,
    )


def _pn_format_generic_table(value, max_rows=20, max_cols=8, max_width=24):
    if isinstance(value, dict):
        headers = ["key", "value"]
        rows = [[key, item] for key, item in list(value.items())[:max_rows]]
        if len(value) > max_rows:
            rows.append(["…", "…"])
        aligns = [False, all(_pn_is_number(row[1]) for row in rows if row[1] != "…")]
        return _pn_box_table(headers, rows, aligns, max_width=max_width)

    if isinstance(value, (list, tuple)):
        items = list(value)
        if not items:
            return "(empty)"

        sample = items[0]
        if isinstance(sample, dict):
            headers = list(sample.keys())[:max_cols]
            rows = [
                [item.get(header, "") for header in headers]
                for item in items[:max_rows]
            ]
            if len(items) > max_rows:
                rows.append(["…"] * len(headers))
            aligns = []
            for column_index in range(len(headers)):
                column_values = [row[column_index] for row in rows if row[column_index] != "…"]
                aligns.append(
                    bool(column_values) and all(_pn_is_number(column) for column in column_values)
                )
            return _pn_box_table(headers, rows, aligns, max_width=max_width)

        if isinstance(sample, (list, tuple)):
            width = min(max_cols, max(len(row) for row in items[:max_rows]))
            headers = [f"c{index + 1}" for index in range(width)]
            rows = [list(row)[:width] for row in items[:max_rows]]
            if len(items) > max_rows:
                rows.append(["…"] * len(headers))
            aligns = []
            for column_index in range(len(headers)):
                column_values = [row[column_index] for row in rows if row[column_index] != "…"]
                aligns.append(
                    bool(column_values) and all(_pn_is_number(column) for column in column_values)
                )
            return _pn_box_table(headers, rows, aligns, max_width=max_width)

        headers = ["#", "value"]
        rows = [[index, item] for index, item in enumerate(items[:max_rows])]
        if len(items) > max_rows:
            rows.append(["…", "…"])
        aligns = [True, all(_pn_is_number(row[1]) for row in rows if row[1] != "…")]
        return _pn_box_table(headers, rows, aligns, max_width=max_width)

    return _pn_clip(value, max_width=max_width)


def table(value, max_rows=20, max_cols=8, max_width=24):
    try:
        import pandas as _pn_pd
    except Exception:
        _pn_pd = None

    if _pn_pd is not None:
        if isinstance(value, _pn_pd.DataFrame):
            return _PNRenderable(
                _pn_format_dataframe(
                    value,
                    max_rows=max_rows,
                    max_cols=max_cols,
                    max_width=max_width,
                )
            )
        if isinstance(value, _pn_pd.Series):
            return _PNRenderable(
                _pn_format_series(
                    value,
                    max_rows=max_rows,
                    max_width=max_width,
                )
            )

    return _PNRenderable(
        _pn_format_generic_table(
            value,
            max_rows=max_rows,
            max_cols=max_cols,
            max_width=max_width,
        )
    )


def _pn_coerce_plot_values(value):
    try:
        import pandas as _pn_pd
    except Exception:
        _pn_pd = None

    if _pn_pd is not None:
        if isinstance(value, _pn_pd.DataFrame):
            if len(value.columns) == 0:
                return []
            value = value.iloc[:, 0].tolist()
        elif isinstance(value, _pn_pd.Series):
            value = value.tolist()

    if hasattr(value, "tolist") and not isinstance(value, (list, tuple, dict, str, bytes)):
        value = value.tolist()

    if isinstance(value, dict):
        value = list(value.values())

    if not isinstance(value, (list, tuple)):
        raise TypeError("plot() expects a sequence, pandas Series, or single-column DataFrame.")

    if value and isinstance(value[0], (list, tuple)) and len(value[0]) >= 2:
        value = [item[1] for item in value]

    numbers = []
    for item in value:
        try:
            number = float(item)
        except Exception:
            continue
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def _pn_resample(values, width):
    if not values:
        return []
    if len(values) == 1:
        return [values[0]] * width

    scale = (len(values) - 1) / max(1, width - 1)
    sampled = []
    for index in range(width):
        position = index * scale
        left = int(math.floor(position))
        right = min(left + 1, len(values) - 1)
        fraction = position - left
        sampled.append(values[left] + (values[right] - values[left]) * fraction)
    return sampled


def _pn_render_plot(values, width=60, height=12):
    if not values:
        return "(no plottable numeric data)"

    width = max(8, int(width))
    height = max(4, int(height))
    sampled = _pn_resample(values, width)
    min_value = min(sampled)
    max_value = max(sampled)
    span = max_value - min_value
    midpoint = (min_value + max_value) / 2.0
    rows = [[" "] * len(sampled) for _ in range(height)]

    previous_row = None
    for column, value in enumerate(sampled):
        if span == 0:
            row = height // 2
        else:
            ratio = (value - min_value) / span
            row = height - 1 - int(round(ratio * (height - 1)))
        if previous_row is not None:
            if row == previous_row and column > 0 and rows[row][column - 1] == " ":
                rows[row][column - 1] = "─"
            elif column > 0:
                step = 1 if row > previous_row else -1
                for fill in range(previous_row + step, row, step):
                    if rows[fill][column - 1] == " ":
                        rows[fill][column - 1] = "│"
                connector = "╲" if row > previous_row else "╱"
                if rows[row][column - 1] == " ":
                    rows[row][column - 1] = connector
        rows[row][column] = "●"
        previous_row = row

    label_width = max(
        len(f"{max_value:.3g}"),
        len(f"{min_value:.3g}"),
        len(f"{midpoint:.3g}"),
    )
    lines = []
    for row_index, row in enumerate(rows):
        if row_index == 0:
            label = f"{max_value:.3g}".rjust(label_width)
        elif row_index == height // 2:
            label = f"{midpoint:.3g}".rjust(label_width)
        elif row_index == height - 1:
            label = f"{min_value:.3g}".rjust(label_width)
        else:
            label = " " * label_width
        lines.append(f"{label} │{''.join(row)}")
    lines.append(f"{' ' * label_width} └{'─' * len(sampled)}")
    lines.append(f"n={len(values)}")
    return "\n".join(lines)


def plot(value, width=60, height=12):
    values = _pn_coerce_plot_values(value)
    return _PNRenderable(_pn_render_plot(values, width=width, height=height))


def _pn_install_display_formatters(ipython_shell):
    try:
        import pandas as _pn_pd
    except Exception:
        return

    formatter = ipython_shell.display_formatter.formatters["text/plain"]

    def _pn_df_printer(df, pretty, cycle):
        pretty.text(_pn_format_dataframe(df))

    def _pn_series_printer(series, pretty, cycle):
        pretty.text(_pn_format_series(series))

    formatter.for_type(_pn_pd.DataFrame, _pn_df_printer)
    formatter.for_type(_pn_pd.Series, _pn_series_printer)


def build_bootstrap_code(startup_statements: tuple[str, ...]) -> str:
    """Build idempotent kernel bootstrap code for helpers and startup statements."""
    components = [
        _PNRenderable,
        _pn_is_number,
        _pn_clip,
        _pn_align,
        _pn_box_table,
        _pn_format_dataframe,
        _pn_format_series,
        _pn_format_generic_table,
        table,
        _pn_coerce_plot_values,
        _pn_resample,
        _pn_render_plot,
        plot,
        _pn_install_display_formatters,
    ]
    source = "\n\n".join(
        textwrap.dedent(inspect.getsource(component)) for component in components
    )
    startup_payload = json.dumps(list(startup_statements))
    body = "\n".join(
        [
            "import math",
            "",
            source,
            "",
            '_pn_shell = globals().get("get_ipython", lambda: None)()',
            "if _pn_shell is not None:",
            "    _pn_install_display_formatters(_pn_shell)",
            "",
            f"for _pn_code in {startup_payload}:",
            "    exec(_pn_code, globals())",
            "",
            f'globals()["_POPUP_NOTEBOOK_BOOTSTRAP_VERSION"] = {BOOTSTRAP_VERSION}',
        ]
    ).strip()
    return (
        f"if globals().get('_POPUP_NOTEBOOK_BOOTSTRAP_VERSION') != {BOOTSTRAP_VERSION}:\n"
        + textwrap.indent(body, "    ")
    )
