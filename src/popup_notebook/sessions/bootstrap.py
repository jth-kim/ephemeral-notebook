from __future__ import annotations

import inspect
import json
import textwrap


BOOTSTRAP_VERSION = 2


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
