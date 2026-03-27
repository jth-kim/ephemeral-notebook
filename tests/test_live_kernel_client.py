from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from popup_notebook.sessions.kernel import KernelController, LiveKernelClient

REPO_PYTHON = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"


class LiveKernelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_client_reuses_connection_for_multiple_executions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                controller = KernelController(project, REPO_PYTHON)
                runtime = controller.start()
                client = LiveKernelClient()
                try:
                    await client.ensure_connected(
                        kernel_pid=runtime.pid,
                        connection_file=runtime.connection_file,
                    )
                    await client.bootstrap(("value = 40",))
                    first = await client.execute("value + 2")
                    second = await client.execute("value + 3")
                finally:
                    client.close()
                    controller.shutdown(runtime.pid, runtime.connection_file)

                self.assertIn("42", first.output)
                self.assertIn("43", second.output)
                self.assertEqual(first.execution_count, 1)
                self.assertEqual(second.execution_count, 2)

    async def test_live_client_reconnects_after_kernel_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                controller = KernelController(project, REPO_PYTHON)
                runtime = controller.start()
                client = LiveKernelClient()
                try:
                    await client.ensure_connected(
                        kernel_pid=runtime.pid,
                        connection_file=runtime.connection_file,
                    )
                    first = await client.execute("21 * 2")

                    runtime = controller.restart(
                        existing_pid=runtime.pid,
                        existing_connection_file=runtime.connection_file,
                    )
                    await client.ensure_connected(
                        kernel_pid=runtime.pid,
                        connection_file=runtime.connection_file,
                    )
                    second = await client.execute("6 * 7")
                finally:
                    client.close()
                    controller.shutdown(runtime.pid, runtime.connection_file)

                self.assertIn("42", first.output)
                self.assertIn("42", second.output)

    async def test_live_client_completes_against_kernel_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                controller = KernelController(project, REPO_PYTHON)
                runtime = controller.start()
                client = LiveKernelClient()
                try:
                    await client.ensure_connected(
                        kernel_pid=runtime.pid,
                        connection_file=runtime.connection_file,
                    )
                    await client.execute("alpha_series = [1, 2, 3]")
                    completion = await client.complete("alpha_ser", len("alpha_ser"))
                    dotted = await client.complete("alpha_series.app", len("alpha_series.app"))
                finally:
                    client.close()
                    controller.shutdown(runtime.pid, runtime.connection_file)

                self.assertIn("alpha_series", completion.matches)
                self.assertGreaterEqual(completion.cursor_end, completion.cursor_start)
                self.assertIn("append", dotted.matches)


if __name__ == "__main__":
    unittest.main()
