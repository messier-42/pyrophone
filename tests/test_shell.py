"""The stdio shell shares the graph loop and participates in its shutdown."""

import asyncio
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def write_script(tmp_path: Path, behavior: str = "forever") -> Path:
    script = tmp_path / "application.py"
    finish = {
        "forever": "await asyncio.Event().wait()",
        "finish": "await asyncio.sleep(0.1)",
        "fail": "await asyncio.sleep(0.1)\n            raise ValueError('node failed')",
    }[behavior]
    script.write_text(
        "import asyncio\n"
        "from pyrophone.script import *\n"
        "@node_type\n"
        "class Worker(Node):\n"
        "    ticks = 0\n"
        "    async def run(self):\n"
        "        print('STARTED', flush=True)\n"
        "        try:\n"
        "            type(self).ticks += 1\n"
        f"            {finish}\n"
        "        finally:\n"
        "            print('CLEANED', flush=True)\n"
        "@main\n"
        "async def application():\n"
        "    return Graph(NodeDeclaration(Worker))\n"
    )
    return script


@pytest.mark.parametrize("ending", ["", "exit()\n", "quit()\n"])
def test_shell_evaluates_python_and_await_while_graph_runs(
    tmp_path: Path, ending: str
) -> None:
    script = write_script(tmp_path)
    commands = (
        "await asyncio.sleep(0.05)\n"
        "print('RUNNING', graph.nodes[0].node_type.ticks, not graph_task.done())\n"
        "print('SNAPSHOT', len(compiled_graph.nodes))\n"
        "print('API', pyrophone.Graph is Graph, mqtt.Source is not None)\n"
        "1 / 0\n"
        "for value in range(2):\n"
        "    print('LOOP', value)\n\n"
        "print('RECOVERED')\n" + ending
    )
    result = subprocess.run(
        [sys.executable, str(script), "--pp-shell"],
        input=commands,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "STARTED\nCLEANED\n"
    assert "RUNNING 1 True" in result.stderr
    assert "SNAPSHOT 1" in result.stderr
    assert "API True True" in result.stderr
    assert "ZeroDivisionError" in result.stderr
    assert "LOOP 0" in result.stderr and "LOOP 1" in result.stderr
    assert "RECOVERED" in result.stderr
    assert "CancelledError" not in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["finish", "fail"])
@pytest.mark.parametrize("command", [b"", b"await asyncio.sleep(3600)\n"])
async def test_graph_completion_or_failure_closes_idle_or_awaiting_shell(
    tmp_path: Path, behavior: str, command: bytes
) -> None:
    script = write_script(tmp_path, behavior)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--pp-shell",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stderr is not None
    assert process.stdout is not None
    try:
        async with asyncio.timeout(10):
            banner = await process.stderr.readuntil(b">>> ")
            process.stdin.write(command)
            await process.stdin.drain()
            # Keep stdin open: runtime completion must interrupt the shell itself.
            stdout, stderr, _ = await asyncio.gather(
                process.stdout.read(), process.stderr.read(), process.wait()
            )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert stdout == b"STARTED\nCLEANED\n"
    assert b"Pyrophone" in banner
    assert process.returncode == (0 if behavior == "finish" else 1)
    if behavior == "fail":
        assert b"node failed" in stderr and b"NodeExecutionError" in stderr
    else:
        assert b"Traceback" not in stderr
    assert b"CancelledError" not in stderr


@pytest.mark.asyncio
async def test_ctrl_c_interrupts_shell_command_without_stopping_graph(
    tmp_path: Path,
) -> None:
    script = write_script(tmp_path)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--pp-shell",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None and process.stderr is not None
    assert process.stdout is not None
    try:
        async with asyncio.timeout(10):
            await process.stderr.readuntil(b">>> ")
            process.stdin.write(b"print('WAITING'); await asyncio.sleep(3600)\n")
            await process.stdin.drain()
            await process.stderr.readuntil(b"WAITING\n")
            process.send_signal(signal.SIGINT)
            interrupted = await process.stderr.readuntil(b">>> ")
            process.stdin.write(b"print('ALIVE', not graph_task.done()); exit()\n")
            await process.stdin.drain()
            stdout, stderr = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == 0, stderr
    assert b"KeyboardInterrupt" in interrupted
    assert b"ALIVE True" in stderr
    assert stdout == b"STARTED\nCLEANED\n"


def test_dump_takes_precedence_over_shell(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(write_script(tmp_path)), "--pp-shell", "--pp-dump-graph"],
        input="raise RuntimeError('shell should not start')\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert len(yaml.safe_load(result.stdout)["nodes"]) == 1
    assert result.stderr == ""


def test_show_graph_precedes_shell(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(write_script(tmp_path)), "--pp-shell", "--pp-show-graph"],
        input="await asyncio.sleep(0.02)\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.index("Graph: 1 nodes") < result.stderr.index(
        "Pyrophone shell"
    )
    assert result.stdout == "STARTED\nCLEANED\n"


def test_shell_exit_preserves_node_cleanup_failures(tmp_path: Path) -> None:
    script = write_script(tmp_path)
    script.write_text(
        script.read_text().replace(
            "            print('CLEANED', flush=True)",
            "            print('CLEANED', flush=True)\n"
            "            raise ValueError('cleanup failed')",
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), "--pp-shell"],
        input="await asyncio.sleep(0.02)\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == "STARTED\nCLEANED\n"
    assert "cleanup failed" in result.stderr
    assert "NodeExecutionError" in result.stderr


def test_terminal_output_restores_handlers_and_preserves_redirected_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import logging

    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.output import DummyOutput

    from pyrophone._terminal import coordinated_output

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    terminal, redirected, file_output = Terminal(), io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setattr(sys, "stdout", redirected)
    console_handler = logging.StreamHandler(terminal)
    file_handler = logging.StreamHandler(file_output)
    stdout_handler = logging.StreamHandler(redirected)
    logger = logging.getLogger("pyrophone.test.terminal")
    monkeypatch.setattr(
        logger, "handlers", [console_handler, file_handler, stdout_handler]
    )
    with create_app_session(output=DummyOutput()):
        with pytest.raises(RuntimeError, match="end session"), coordinated_output():
            assert console_handler.stream is sys.stderr
            assert sys.stderr is not terminal
            assert sys.stdout is redirected
            assert stdout_handler.stream is redirected
            assert file_handler.stream is file_output
            created_in_shell = logging.StreamHandler()
            logger.addHandler(created_in_shell)
            raise RuntimeError("end session")
    assert sys.stderr is terminal and sys.stdout is redirected
    assert console_handler.stream is terminal
    assert created_in_shell.stream is terminal
    assert stdout_handler.stream is redirected
    assert file_handler.stream is file_output
