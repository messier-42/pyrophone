"""JQ maps complete JSON messages to an ordered stream of JSON messages."""

import asyncio
import importlib
import json
import subprocess
import sys
from collections.abc import Callable
from types import ModuleType

import pytest

import pyrophone as pp


def test_jq_import_and_schema_do_not_require_optional_dependency() -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.modules['jq'] = None; "
            "from pyrophone.script import JQ; "
            "from pyrophone import NodeDeclaration, node_type_schema; "
            "node = NodeDeclaration(JQ, {'expr': '.count += 1'}); "
            "schema = node_type_schema(JQ); "
            "assert schema.inputs['in_port'].type is bytes; "
            "assert schema.outputs['out_port'].type is bytes; "
            "assert schema.properties['expr'].required",
        ],
        check=True,
    )


async def pipeline(
    program: str,
    payloads: list[bytes],
    on_value: Callable[[pp.Runtime, bytes], None] | None = None,
) -> list[bytes]:
    from pyrophone.jq import JQ

    received: list[bytes] = []
    controllers: list[pp.Runtime] = []

    @pp.node_type
    class Source(pp.Node):
        out_port = pp.Output[bytes]()

        async def run(self) -> None:
            for payload in payloads:
                await self.out_port.send(payload)

    @pp.node_type
    class Sink(pp.Node):
        in_port = pp.Input[bytes]()

        async def run(self) -> None:
            async for value in self.in_port:
                received.append(value)
                if on_value is not None:
                    on_value(controllers[0], value)

    graph = (
        pp.NodeDeclaration(Source)
        | pp.NodeDeclaration(JQ, {"expr": program})
        | pp.NodeDeclaration(Sink)
    )
    async with asyncio.timeout(2):
        await pp.run_async(graph, on_runtime=controllers.append)
    return received


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("program", "payloads", "expected"),
    [
        (".count += 1", [b'{"count":0,"name":"demo"}'], [b'{"count":1,"name":"demo"}']),
        (".[]", [b"[1,2]", b"[3]"], [b"1", b"2", b"3"]),
        ("select(.count > 0)", [b'{"count":0}', b'{"count":2}'], [b'{"count":2}']),
        ("empty", [b"null", b"{}"], []),
        (
            ".",
            [b"null", b"false", b"42", '"café"'.encode()],
            [b"null", b"false", b"42", '"café"'.encode()],
        ),
        ("[.[] + 1]", [b"[1,2]"], [b"[2,3]"]),
    ],
)
async def test_real_jq_results(
    program: str, payloads: list[bytes], expected: list[bytes]
) -> None:
    pytest.importorskip("jq")
    assert await pipeline(program, payloads) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("program", "payload"),
    [
        ("[", b"{}"),
        (".", b"not json"),
        (".", b"1 2"),
        ('error("bad input")', b"null"),
    ],
)
async def test_program_input_and_evaluation_errors_fail_the_node(
    program: str, payload: bytes
) -> None:
    pytest.importorskip("jq")
    with pytest.raises(ExceptionGroup) as caught:
        await pipeline(program, [payload])
    assert any(
        isinstance(error, pp.NodeExecutionError) and error.node_type_name == "JQ"
        for error in caught.value.exceptions
    )


@pytest.mark.asyncio
async def test_expression_is_reused_and_live_change_starts_with_next_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_jq = pytest.importorskip("jq")
    module = importlib.import_module("pyrophone.jq")
    calls: list[str] = []
    api = ModuleType("jq")

    def compile_program(program: str) -> object:
        calls.append(program)
        return real_jq.compile(program)

    monkeypatch.setattr(api, "compile", compile_program, raising=False)
    monkeypatch.setattr(module, "import_module", lambda name: api)

    def update(runtime: pp.Runtime, value: bytes) -> None:
        if json.loads(value) == 1:
            runtime.nodes[1].expr = ".[] + 10"

    assert await pipeline(".[]", [b"[1,2]", b"[3]", b"[4]"], update) == [
        b"1",
        b"2",
        b"13",
        b"14",
    ]
    assert calls == [".[]", ".[] + 10"]


@pytest.mark.asyncio
async def test_missing_dependency_has_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("pyrophone.jq")

    def missing(name: str) -> ModuleType:
        raise ModuleNotFoundError("No module named jq", name="jq")

    monkeypatch.setattr(module, "import_module", missing)
    with pytest.raises(ExceptionGroup) as caught:
        await pipeline(".", [b"null"])
    assert any(
        isinstance(error.__cause__, ImportError)
        and "Pyrophone[jq]" in str(error.__cause__)
        for error in caught.value.exceptions
    )
