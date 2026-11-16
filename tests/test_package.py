"""Smoke checks for the installed package."""

import subprocess
import sys


def test_import_without_cabe() -> None:
    """Importing the DSL must not load its optional CABE integration."""
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import pyrophone; import sys; assert 'cabe' not in sys.modules",
        ],
        check=True,
    )
