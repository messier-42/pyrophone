"""Script entry points own an event loop without changing imported factories."""

import asyncio
import runpy
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

import pyrophone as pp


@pp.node_type
class Report(pp.Node):
    async def run(self) -> None:
        print("ran")


def test_run_sync_executes_graph(capsys: pytest.CaptureFixture[str]) -> None:
    pp.run_sync(pp.Graph(pp.NodeDeclaration(Report)))
    assert capsys.readouterr().out == "ran\n"


@pytest.mark.asyncio
async def test_run_async_executes_graph(capsys: pytest.CaptureFixture[str]) -> None:
    await pp.run_async(pp.Graph(pp.NodeDeclaration(Report)))
    assert capsys.readouterr().out == "ran\n"
    assert pp.run is pp.run_async


@pytest.mark.asyncio
async def test_run_sync_rejects_existing_loop_without_creating_coroutine() -> None:
    with pytest.raises(RuntimeError, match="run_async"):
        pp.run_sync(pp.Graph())


def test_main_graph_routes_to_run_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    import pyrophone._driver as driver

    graphs: list[pp.Graph] = []
    monkeypatch.setattr(driver, "run_sync", graphs.append)
    monkeypatch.setattr(sys, "argv", ["demo.py"])
    graph = pp.Graph()
    assert pp.main(graph) is None
    assert graphs == [graph]


@pytest.mark.parametrize("decorator", ["@main", "@main()"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_decorator_runs_only_as_entry_point(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decorator: str,
    asynchronous: bool,
) -> None:
    script = tmp_path / "demo.py"
    definition = "async def" if asynchronous else "def"
    setup = "    await asyncio.sleep(0)\n" if asynchronous else ""
    script.write_text(
        "from pyrophone.script import *\n"
        "import asyncio\n"
        "@node_type\n"
        "class Report(Node):\n"
        "    async def run(self):\n"
        "        print('ran')\n"
        f"{decorator}\n{definition} application():\n"
        "    print('built')\n"
        f"{setup}"
        "    return Graph(NodeDeclaration(Report))\n"
        "print('loaded')\n"
    )
    namespace = runpy.run_path(str(script))
    assert capsys.readouterr().out == "loaded\n"
    assert callable(namespace["application"])
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    )
    assert result.stdout == "built\nran\nloaded\n"
    assert result.stderr == ""


def test_imported_decorator_preserves_function_identity() -> None:
    def build() -> pp.Graph:
        return pp.Graph()

    async def build_async() -> pp.Graph:
        return pp.Graph()

    assert pp.main(build) is build
    assert pp.main()(build) is build
    assert pp.main(build_async) is build_async
    assert pp.main()(build_async) is build_async
    assert isinstance(build(), pp.Graph)
    assert isinstance(asyncio.run(build_async()), pp.Graph)


def test_async_factory_and_nodes_share_event_loop(tmp_path: Path) -> None:
    script = tmp_path / "demo.py"
    script.write_text(
        "import asyncio\n"
        "from pyrophone.script import *\n"
        "@main\n"
        "async def application():\n"
        "    loop = asyncio.get_running_loop()\n"
        "    @node_type\n"
        "    class Report(Node):\n"
        "        async def run(self):\n"
        "            assert asyncio.get_running_loop() is loop\n"
        "    return Graph(NodeDeclaration(Report))\n"
    )
    subprocess.run([sys.executable, str(script)], check=True)


@pytest.mark.parametrize("result", ["None", "42"])
def test_factory_must_return_graph(tmp_path: Path, result: str) -> None:
    script = tmp_path / "demo.py"
    script.write_text(
        f"from pyrophone import main\n@main\ndef application():\n    return {result}\n"
    )
    process = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True
    )
    assert process.returncode != 0
    assert "TypeError" in process.stderr and "Graph" in process.stderr


def test_run_sync_preserves_node_failures() -> None:
    @pp.node_type
    class Broken(pp.Node):
        async def run(self) -> None:
            raise ValueError("broken")

    with pytest.raises(ExceptionGroup) as caught:
        pp.run_sync(pp.Graph(pp.NodeDeclaration(Broken)))
    error = cast(pp.NodeExecutionError, caught.value.exceptions[0])
    assert isinstance(error, pp.NodeExecutionError)
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize(
    "entry", ["run_sync(graph)", "main(graph)", "@main\ndef app():\n    return graph"]
)
def test_ctrl_c_cleans_up_without_traceback(tmp_path: Path, entry: str) -> None:
    script = tmp_path / "demo.py"
    script.write_text(
        "import asyncio, signal\n"
        "from pyrophone.script import *\n"
        "@node_type\n"
        "class Worker(Node):\n"
        "    async def run(self):\n"
        "        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)\n"
        "        try:\n"
        "            await asyncio.Event().wait()\n"
        "        finally:\n"
        "            print('cleaned up')\n"
        "graph = Graph(NodeDeclaration(Worker))\n"
        f"{entry}\n"
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "cleaned up\n"
    assert result.stderr == ""


def test_script_import_needs_no_optional_dependencies() -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.modules['aiomqtt'] = None; "
            "from pyrophone.script import *; "
            "assert pyrophone.main is main; assert mqtt.Source; "
            "assert PrintBytes; assert JSONTransform; assert Property; "
            "assert sys.modules['aiomqtt'] is None",
        ],
        check=True,
    )


@pytest.mark.parametrize(
    "entry",
    [
        "main(graph)",
        "@main\ndef app():\n    print('built')\n    return graph",
        "@main()\ndef app():\n    print('built')\n    return graph",
        "@main\nasync def app():\n    print('built')\n    return graph",
        "@main()\nasync def app():\n    print('built')\n    return graph",
    ],
)
@pytest.mark.parametrize("argument", ["--help", "--unknown", "unexpected"])
def test_main_parses_arguments_before_building_or_running(
    tmp_path: Path, entry: str, argument: str
) -> None:
    script = tmp_path / "demo.py"
    script.write_text(
        "from pyrophone.script import *\n"
        "@node_type\n"
        "class Worker(Node):\n"
        "    async def run(self):\n"
        "        print('ran')\n"
        "graph = Graph(NodeDeclaration(Worker))\n"
        f"{entry}\n"
    )
    result = subprocess.run(
        [sys.executable, str(script), argument],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (0 if argument == "--help" else 2)
    output = result.stdout if argument == "--help" else result.stderr
    assert "usage: demo.py" in output
    assert "built" not in result.stdout
    assert "ran" not in result.stdout
    if argument != "--help":
        assert "unrecognized arguments:" in result.stderr


def test_run_sync_does_not_parse_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["application.py", "--unrelated-option"])
    pp.run_sync(pp.Graph(pp.NodeDeclaration(Report)))
    assert capsys.readouterr().out == "ran\n"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_run_sync_accepts_graph_factory(
    capsys: pytest.CaptureFixture[str], asynchronous: bool
) -> None:
    def build() -> pp.Graph:
        return pp.Graph(pp.NodeDeclaration(Report))

    async def build_async() -> pp.Graph:
        await asyncio.sleep(0)
        return build()

    pp.run_sync(build_async if asynchronous else build)
    assert capsys.readouterr().out == "ran\n"
