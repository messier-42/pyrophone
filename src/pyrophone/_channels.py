"""Unbuffered, FIFO handoff between asynchronous producer and consumer ports."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ._exceptions import ChannelClosedError, EndOfStream


@dataclass(eq=False)
class _PendingSend[T]:
    value: T
    accepted: asyncio.Future[None]


class Channel[T]:
    """One edge's rendezvous state, confined to one asyncio event loop.

    Waiters are matched in arrival order. A handoff accepts the value immediately;
    cancellation after acceptance does not undo delivery. Pending sends retain
    their values only while the sender is waiting, never as buffered arrivals.
    Closing either end rejects unaccepted sends and ends outstanding receives.
    """

    def __init__(self) -> None:
        self._closed = False
        self._senders: deque[_PendingSend[T]] = deque()
        self._receivers: deque[asyncio.Future[T]] = deque()
        self.input = ReceiveEndpoint(self)
        self.output = SendEndpoint(self)

    async def _send(self, value: T) -> None:
        if self._closed:
            raise ChannelClosedError("channel is closed")
        while self._receivers:
            receiver = self._receivers.popleft()
            if not receiver.done():
                receiver.set_result(value)
                return
        accepted: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        pending = _PendingSend(value, accepted)
        self._senders.append(pending)
        try:
            await accepted
        finally:
            # A matched or closed waiter has already been removed.
            if pending in self._senders:
                self._senders.remove(pending)

    async def _recv(self) -> T:
        while self._senders:
            pending = self._senders.popleft()
            if not pending.accepted.done():
                pending.accepted.set_result(None)
                return pending.value
        if self._closed:
            raise EndOfStream("channel is closed")
        receiver: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._receivers.append(receiver)
        try:
            return await receiver
        finally:
            if receiver in self._receivers:
                self._receivers.remove(receiver)

    def _close(self) -> None:
        self._closed = True
        while self._senders:
            pending = self._senders.popleft()
            if not pending.accepted.done():
                pending.accepted.set_exception(ChannelClosedError("channel is closed"))
        while self._receivers:
            receiver = self._receivers.popleft()
            if not receiver.done():
                receiver.set_exception(EndOfStream("channel is closed"))


class ReceiveEndpoint[T]:
    """Consumer view of a channel; closing withdraws consumer interest."""

    def __init__(self, channel: Channel[T]) -> None:
        self._channel = channel

    async def recv(self) -> T:
        return await self._channel._recv()

    async def close(self) -> None:
        self._channel._close()

    async def __aiter__(self) -> AsyncIterator[T]:
        while True:
            try:
                value = await self.recv()
            except EndOfStream:
                return
            yield value


class SendEndpoint[T]:
    """Producer view of a channel; closing announces end of stream."""

    def __init__(self, channel: Channel[T]) -> None:
        self._channel = channel

    async def send(self, value: T) -> None:
        await self._channel._send(value)

    async def close(self) -> None:
        self._channel._close()
