import subprocess
import sys
from pathlib import Path


def check_snippet(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    snippet = tmp_path / "snippet.py"
    snippet.write_text(source)
    config = tmp_path / "mypy.ini"
    config.write_text("[mypy]\npython_version = 3.12\nstrict = True\n")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--no-incremental",
            "--show-error-codes",
            str(snippet),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_descriptors_and_endpoints_preserve_static_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone import Node, Property, Input, Output, InputPort, OutputPort, node_type

@node_type
class Add(Node):
    amount = Property[int](default=1)
    in_port = Input[int]()
    out_port = Output[int]()

    async def run(self) -> None:
        assert_type(self.amount, int)
        assert_type(self.in_port, InputPort[int])
        assert_type(self.out_port, OutputPort[int])
        assert_type(await self.in_port.recv(), int)
        async for value in self.in_port:
            assert_type(value, int)
            await self.out_port.send(value + self.amount)

class Base[T](Node):
    in_port = Input[T]()
    out_port = Output[T]()

@node_type
class Concrete(Base[int]):
    async def run(self) -> None:
        assert_type(await self.in_port.recv(), int)
        await self.out_port.send(2)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_assignments_and_sends_are_rejected(tmp_path: Path) -> None:
    source = """
from pyrophone import Node, Property, Input, Output

class Bad(Node):
    amount = Property[int](default=1)
    in_port = Input[int]()
    out_port = Output[int]()

    async def run(self) -> None:
        self.amount = 2
        self.in_port = self.in_port
        self.out_port = self.out_port
        await self.out_port.send("wrong")
"""
    result = check_snippet(tmp_path, source)
    assert result.returncode == 1, result.stdout + result.stderr
    for line in (10, 11, 12):
        assert f"snippet.py:{line}: error:" in result.stdout, result.stdout
        assert any(
            f"snippet.py:{line}:" in diagnostic and "Never" in diagnostic
            for diagnostic in result.stdout.splitlines()
        ), result.stdout
    assert 'snippet.py:13: error: Argument 1 to "send"' in result.stdout
    assert 'expected "int"' in result.stdout
