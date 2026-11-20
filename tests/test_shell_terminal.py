"""Real terminal output preserves an in-progress Python command and cursor."""

import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pyte
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY test")


@pytest.mark.parametrize("ending", [b"exit()\n", b"\x04"])
def test_logs_redraw_above_partial_command(tmp_path: Path, ending: bytes) -> None:
    import pty

    trigger = tmp_path / "emit"
    script = tmp_path / "terminal.py"
    script.write_text(
        "import asyncio, logging\n"
        "from pathlib import Path\n"
        "from pyrophone.script import *\n"
        "logging.basicConfig(level=logging.INFO, format='%(message)s')\n"
        "@node_type\n"
        "class Worker(Node):\n"
        "    async def run(self):\n"
        "        try:\n"
        f"            while not Path({str(trigger)!r}).exists():\n"
        "                await asyncio.sleep(0.01)\n"
        "            await asyncio.to_thread(logging.warning, 'LOG_ONE')\n"
        "            print('PRINT_TWO', flush=True)\n"
        "            logging.warning('LOG_THREE')\n"
        "            await asyncio.Event().wait()\n"
        "        finally:\n"
        "            print('CLEANED', flush=True)\n"
        "main(Graph(NodeDeclaration(Worker)))\n"
    )
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, str(script), "--pp-shell"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "TERM": "xterm", "PROMPT_TOOLKIT_NO_CPR": "1"},
    )
    os.close(slave)
    screen = pyte.Screen(80, 40)
    stream = pyte.ByteStream(screen)

    def read_until(predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 8
        while not predicate():
            remaining = deadline - time.monotonic()
            assert remaining > 0, "\n".join(screen.display)
            if select.select([master], [], [], remaining)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    pytest.fail("Terminal closed: " + "\n".join(screen.display))
                assert chunk
                stream.feed(chunk)

    def has_line(text: str) -> bool:
        return any(line.rstrip() == text for line in screen.display)

    try:
        read_until(lambda: has_line(">>> ".rstrip()))
        os.write(master, b"print('KEEP')\x1b[D\x1b[D")
        read_until(lambda: has_line(">>> print('KEEP')") and screen.cursor.x == 15)
        trigger.touch()
        read_until(
            lambda: all(
                has_line(line)
                for line in ("LOG_ONE", "PRINT_TWO", "LOG_THREE", ">>> print('KEEP')")
            )
        )
        assert screen.cursor.x == 15
        os.write(master, b"_VALUE\n")
        read_until(lambda: has_line("KEEP_VALUE"))
        os.write(master, b"unfinished\x03")
        read_until(
            lambda: (
                has_line("KeyboardInterrupt")
                and screen.display[screen.cursor.y].rstrip() == ">>>"
            )
        )
        os.write(master, ending)
        read_until(lambda: has_line("CLEANED"))
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGKILL)
        process.wait(timeout=5)
        os.close(master)
