"""Rendezvous acceptance, closure, and cancellation contracts."""

import asyncio
from collections.abc import Awaitable

import pytest

import pyrophone as pp
from pyrophone._channels import Channel


async def start[T](
    tasks: asyncio.TaskGroup, operation: Awaitable[T]
) -> asyncio.Task[T]:
    entered = asyncio.Event()

    async def perform() -> T:
        entered.set()
        return await operation

    task = tasks.create_task(perform())
    await entered.wait()
    return task


@pytest.mark.asyncio
async def test_send_waits_for_acceptance_not_processing() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, channel.output.send(1))
        second = await start(tasks, channel.output.send(2))
        assert not first.done() and not second.done()
        assert await channel.input.recv() == 1
        await first
        assert not second.done()
        assert await channel.input.recv() == 2
        await second


@pytest.mark.asyncio
async def test_receivers_can_arrive_first_in_fifo_order() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, channel.input.recv())
        second = await start(tasks, channel.input.recv())
        assert not first.done() and not second.done()
        await channel.output.send(1)
        await channel.output.send(2)
        assert await first == 1
        assert await second == 2


async def receive_end(channel: Channel[int]) -> None:
    with pytest.raises(pp.EndOfStream):
        await channel.input.recv()


async def send_closed(channel: Channel[int], value: int = 1) -> None:
    with pytest.raises(pp.ChannelClosedError):
        await channel.output.send(value)


@pytest.mark.asyncio
async def test_producer_close_wakes_all_readers() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, receive_end(channel))
        second = await start(tasks, receive_end(channel))
        await channel.output.close()
        await channel.output.close()
        await first
        await second
        await receive_end(channel)
        await send_closed(channel)
        assert [value async for value in channel.input] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["input", "output"])
async def test_close_rejects_all_unaccepted_sends(end: str) -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, send_closed(channel, 1))
        second = await start(tasks, send_closed(channel, 2))
        if end == "input":
            await channel.input.close()
            await channel.input.close()
        else:
            await channel.output.close()
            await channel.output.close()
        await first
        await second
        await receive_end(channel)
        await send_closed(channel)


@pytest.mark.asyncio
async def test_cancelled_pending_send_withdraws_value() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, channel.output.send(1))
        second = await start(tasks, channel.output.send(2))
        first.cancel()
        # Receive before the cancelled sender's finally has run.
        assert await channel.input.recv() == 2
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        await channel.output.close()
        await receive_end(channel)


@pytest.mark.asyncio
async def test_cancelled_receiver_does_not_consume_later_value() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        first = await start(tasks, channel.input.recv())
        first.cancel()
        sender = await start(tasks, channel.output.send(9))
        assert not sender.done()
        assert await channel.input.recv() == 9
        with pytest.raises(asyncio.CancelledError):
            await first
        await sender


@pytest.mark.asyncio
async def test_iteration_yields_raw_values_and_only_swallows_end() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()

        async def produce() -> None:
            await channel.output.send(0)
            await channel.output.send(7)
            await channel.output.close()

        producer = await start(tasks, produce())
        assert [value async for value in channel.input] == [0, 7]
        await producer

        other = Channel[int]()
        iterator = other.input.__aiter__()
        pending = await start(tasks, anext(iterator))
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await other.input.close()


@pytest.mark.asyncio
async def test_waiter_cancellation_does_not_compare_message_values() -> None:
    class Opaque:
        def __eq__(self, other: object) -> bool:
            raise AssertionError("transport must not compare messages")

    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[Opaque]()
        value = Opaque()
        first = await start(tasks, channel.output.send(value))
        second = await start(tasks, channel.output.send(Opaque()))
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert await channel.input.recv() is value
        await first


@pytest.mark.asyncio
async def test_close_does_not_revoke_an_accepted_handoff() -> None:
    async with asyncio.timeout(2), asyncio.TaskGroup() as tasks:
        channel = Channel[int]()
        receiver = await start(tasks, channel.input.recv())
        await channel.output.send(3)
        await channel.output.close()
        assert await receiver == 3
        await receive_end(channel)
