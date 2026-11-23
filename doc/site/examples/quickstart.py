from pyrophone.script import *
import asyncio

@node_type
class Greeting(Source[str]):
    async def produce(self):
        while True:
            yield "hello, pyrophone"
            await asyncio.sleep(1)

@node_type
class Uppercase(Transform[str, str]):
    async def transform(self, value: str) -> str:
        return value.upper()

@node_type
class Display(Sink[str]):
    async def consume(self, message: str):
        print(message, flush=True)

@main
def graph():
    return Greeting() | Uppercase() | Display()
