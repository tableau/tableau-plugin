import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "run_python.py"
SPEC = importlib.util.spec_from_file_location("tableau_run_python", SCRIPT)
RUN_PYTHON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_PYTHON)


class RunPythonTest(unittest.TestCase):
    def test_python_38_never_runs_plugin_script_in_process(self):
        with mock.patch.object(RUN_PYTHON.sys, "version_info", (3, 8)):
            self.assertFalse(RUN_PYTHON.current_satisfies([]))

    def test_python_38_finds_compatible_interpreter_on_path(self):
        def which(name):
            return "/opt/python3.11" if name == "python3.11" else None

        with mock.patch.object(RUN_PYTHON.sys, "version_info", (3, 8)), \
             mock.patch.object(RUN_PYTHON.shutil, "which", side_effect=which), \
             mock.patch.object(RUN_PYTHON, "python_version", return_value=(3, 11)):
            self.assertEqual(
                RUN_PYTHON.compatible_python(),
                ("/opt/python3.11", (3, 11)),
            )

    def test_venv_is_created_with_compatible_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv-3.11"

            def create_venv(*args, **kwargs):
                venv.mkdir(parents=True)

            with mock.patch.object(RUN_PYTHON, "cache_dir", return_value=Path(tmp)), \
                 mock.patch.object(
                     RUN_PYTHON.subprocess, "run", side_effect=create_venv
                 ) as run:
                python = RUN_PYTHON.ensure_venv([], [], None, "/opt/python3.11", (3, 11))

        run.assert_called_once_with(
            ["/opt/python3.11", "-m", "venv", "--clear", str(Path(tmp) / "venv-3.11")],
            check=True,
            stdout=sys.stderr,
        )
        self.assertEqual(python, Path(tmp) / "venv-3.11" / "bin" / "python")


if __name__ == "__main__":
    unittest.main()
