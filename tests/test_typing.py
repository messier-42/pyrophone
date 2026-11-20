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


def test_transform_preserves_distinct_input_and_output_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone import InputPort, OutputPort, Property, node_type
from pyrophone.nodes import Transform

@node_type
class Add(Transform[int, int]):
    amount = Property[int](default=1)

    async def transform(self, value: int) -> int:
        assert_type(value, int)
        assert_type(self.amount, int)
        assert_type(self.in_port, InputPort[int])
        assert_type(self.out_port, OutputPort[int])
        return value + self.amount

@node_type
class Format(Transform[int, str]):
    async def transform(self, value: int) -> str:
        assert_type(self.in_port, InputPort[int])
        assert_type(self.out_port, OutputPort[str])
        assert_type(await self.in_port.recv(), int)
        return str(value)

async def inspect(node: Format) -> None:
    assert_type(await node.transform(1), str)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_transform_rejects_wrong_send_and_result_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from pyrophone.nodes import Transform

class Bad(Transform[int, str]):
    async def transform(self, value: int) -> str:
        await self.out_port.send(value)
        return value
""",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'snippet.py:6: error: Argument 1 to "send"' in result.stdout
    assert "snippet.py:7: error: Incompatible return value type" in result.stdout
    assert 'expected "str"' in result.stdout


def test_json_transform_exposes_json_values_and_byte_ports(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone import InputPort, OutputPort, node_type
from pyrophone.nodes import JSONTransform, JSONValue

@node_type
class Wrap(JSONTransform):
    async def transform_json(self, value: JSONValue) -> JSONValue:
        assert_type(self.in_port, InputPort[bytes])
        assert_type(self.out_port, OutputPort[bytes])
        return {"value": value}

async def inspect(node: Wrap) -> None:
    assert_type(await node.transform(b"null"), bytes)
    assert_type(await node.transform_json(None), JSONValue)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_entry_points_preserve_factory_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone.script import *

@main
def build() -> Graph:
    return Graph()

@main()
def configured() -> Graph:
    return Graph()

@pyrophone.main
async def build_async() -> Graph:
    return Graph()

@pyrophone.main()
async def configured_async() -> Graph:
    return Graph()

assert_type(build(), Graph)
assert_type(configured(), Graph)
assert_type(main(Graph()), None)
assert_type(run_sync(Graph()), None)

async def inspect() -> None:
    assert_type(await build_async(), Graph)
    assert_type(await configured_async(), Graph)
    assert_type(await run_async(Graph()), None)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_identity_preserves_static_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone.script import Identity, IdentityBytes, InputPort, OutputPort, node_type

@node_type
class IdentityInt(Identity[int]):
    pass

async def inspect(identity: IdentityInt, byte_identity: IdentityBytes) -> None:
    assert_type(identity.in_port, InputPort[int])
    assert_type(identity.out_port, OutputPort[int])
    assert_type(await identity.transform(3), int)
    assert_type(await byte_identity.transform(b"value"), bytes)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cabe_transforms_preserve_byte_port_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone.script import cabe, InputPort, OutputPort

async def inspect(enc: cabe.Encapsulator, dec: cabe.Decapsulator) -> None:
    assert_type(enc.in_port, InputPort[bytes])
    assert_type(enc.out_port, OutputPort[bytes])
    assert_type(enc.attrs, dict[str, object])
    assert_type(enc.service, dict[str, object])
    assert_type(await enc.transform(b"payload"), bytes)
    assert_type(dec.in_port, InputPort[bytes])
    assert_type(dec.out_port, OutputPort[bytes])
    assert_type(await dec.transform(b"wire"), bytes)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_jq_exposes_string_expression_and_byte_ports(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone.script import JQ, InputPort, OutputPort

def inspect(node: JQ) -> None:
    assert_type(node.expr, str)
    assert_type(node.in_port, InputPort[bytes])
    assert_type(node.out_port, OutputPort[bytes])
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_print_text_preserves_static_transform_result_types(tmp_path: Path) -> None:
    result = check_snippet(
        tmp_path,
        """
from typing import assert_type
from pyrophone.script import PrintText

async def inspect(printer: PrintText, mixed: str | bytes) -> None:
    assert_type(await printer.transform("text"), str)
    assert_type(await printer.transform(b"text"), bytes)
    assert_type(await printer.transform(mixed), str | bytes)
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
