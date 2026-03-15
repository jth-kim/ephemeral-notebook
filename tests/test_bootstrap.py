from __future__ import annotations

import unittest

from popup_notebook.sessions.bootstrap import BOOTSTRAP_VERSION, build_bootstrap_code


class BootstrapTests(unittest.TestCase):
    def test_build_bootstrap_code_compiles_and_embeds_startup(self) -> None:
        code = build_bootstrap_code(("import numpy as np", "VALUE = 'ok'"))

        self.assertIn("_POPUP_NOTEBOOK_BOOTSTRAP_VERSION", code)
        self.assertIn(str(BOOTSTRAP_VERSION), code)
        self.assertIn("import numpy as np", code)
        self.assertIn("VALUE = 'ok'", code)
        compile(code, "<bootstrap>", "exec")


if __name__ == "__main__":
    unittest.main()
