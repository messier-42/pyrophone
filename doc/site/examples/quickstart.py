"""Route one message through a source, a transform, and a sink."""

from pyrophone.script import Graph, Input, Node, Output, Transform, main, node_type


@node_type
class Greeting(Node):
    out = Output[str]()

    async def run(self) -> None:
        await self.out.send("hello, pyrophone")


@node_type
class Uppercase(Transform[str, str]):
    async def transform(self, value: str) -> str:
        return value.upper()


@node_type
class Display(Node):
    incoming = Input[str]()

    async def run(self) -> None:
        async for message in self.incoming:
            print(message)


@main
def application() -> Graph:
    return Greeting() | Uppercase() | Display()
