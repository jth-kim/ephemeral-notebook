from __future__ import annotations

import asyncio
import unittest

from textual.widgets._text_area import Selection
from textual import events

from popup_notebook.tui.widgets.cell import NotebookTextArea, _pretty_repr_text


class NotebookTextAreaTests(unittest.TestCase):
    def test_python_pairing_inserts_and_wraps(self) -> None:
        area = NotebookTextArea("cell-1", text="", language="python", tab_behavior="indent")
        area.selection = Selection.cursor((0, 0))

        inserted = area._handle_python_pairing("(")

        self.assertTrue(inserted)
        self.assertEqual(area.text, "()")
        self.assertEqual(area.cursor_location, (0, 1))

    def test_python_pairing_skips_existing_closer(self) -> None:
        area = NotebookTextArea("cell-1", text="()", language="python", tab_behavior="indent")
        area.selection = Selection.cursor((0, 1))

        skipped = area._handle_python_pairing(")")

        self.assertTrue(skipped)
        self.assertEqual(area.text, "()")
        self.assertEqual(area.cursor_location, (0, 2))

    def test_pair_character_alias_maps_square_and_curly_brackets(self) -> None:
        left_square = events.Key("left_square_bracket", None)
        left_curly = events.Key("left_curly_bracket", None)

        self.assertEqual(NotebookTextArea._pair_character_from_event(left_square), "[")
        self.assertEqual(NotebookTextArea._pair_character_from_event(left_curly), "{")

    def test_kernel_completion_falls_back_for_plain_words(self) -> None:
        area = NotebookTextArea("cell-1", text="ret", language="python", tab_behavior="indent")
        area.selection = Selection.cursor((0, 3))

        completed = asyncio.run(area._autocomplete_python_token())

        self.assertTrue(completed)
        self.assertEqual(area.text, "return")

    def test_pretty_repr_text_formats_repr_like_outputs(self) -> None:
        rendered = _pretty_repr_text(
            "ProfileReport(summary=df, recommendation='keep', cache_path=PosixPath('x'))"
        )

        self.assertEqual(
            rendered,
            "ProfileReport(\n"
            "  summary=df,\n"
            "  recommendation='keep',\n"
            "  cache_path=PosixPath('x')\n"
            ")",
        )

    def test_pretty_repr_text_leaves_tracebacks_unchanged(self) -> None:
        traceback = "Traceback (most recent call last)\nNameError: x"

        self.assertEqual(_pretty_repr_text(traceback), traceback)


if __name__ == "__main__":
    unittest.main()
