"""Shared fixtures and helpers for all tests."""
import socket
import threading
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

import pytest

from src.testing.ammeter import Ammeter, Measurement
from src.utils.emulators import start_emulators

# Emulator class and its measurement command, as in config.yaml
EMULATORS = {
    "greenlee": ("Ammeters.Greenlee_Ammeter.GreenleeAmmeter", b"MEASURE_GREENLEE -get_measurement"),
    "entes": ("Ammeters.Entes_Ammeter.EntesAmmeter", b"MEASURE_ENTES -get_data"),
    "circutor": ("Ammeters.Circutor_Ammeter.CircutorAmmeter", b"MEASURE_CIRCUTOR -get_measurement"),
}


def free_port() -> int:
    """
    Asks the operating system for a free port, so tests never clash with each other or with a running main.py.

    :returns: A TCP port on localhost that was free a moment ago.
    """
    with socket.socket() as s:
        s.bind(("localhost", 0))  # Port 0 = "any free port"
        return s.getsockname()[1]


@pytest.fixture
def emulator() -> Callable[[str], Ammeter]:
    """
    Factory that starts a real emulator on a free port.

    :returns: Function that takes an ammeter name from :data:`EMULATORS` and returns a ready :class:`Ammeter`.
    """
    def start(name: str) -> Ammeter:
        """
        :param name: ``"greenlee"``, ``"entes"`` or ``"circutor"``.
        :returns: The ammeter; its emulator already accepts connections.
        """
        class_path, command = EMULATORS[name]
        ammeter = Ammeter(name, free_port(), command, emulator=class_path)
        start_emulators({name: ammeter})
        return ammeter
    return start


class FakeServer:
    """
    TCP server that answers every connection the way a test wants, unlike the emulators it can be stopped.

    :ivar port: Port the server listens on.
    :ivar requests: Commands received so far, in order.
    """

    def __init__(self, reply: Callable[[int, bytes], Tuple[float, Optional[Sequence[bytes]]]],
                 chunk_gap: float = 0.0):
        """
        :param reply: Called for the n-th connection (from 0) with the received command; returns a delay in
            seconds before answering and the chunks to send, or ``None`` to send nothing.
        :param chunk_gap: Pause between chunks, so they arrive as separate TCP segments.
        """
        self._reply = reply
        self._chunk_gap = chunk_gap
        self._stop = threading.Event()
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("localhost", 0))
        self._socket.listen()
        self._socket.settimeout(0.05)  # So the loop notices stop() quickly
        self.port = self._socket.getsockname()[1]
        self.requests: List[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        """Accepts connections until :meth:`stop` is called."""
        while not self._stop.is_set():
            try:
                conn, _ = self._socket.accept()
            except socket.timeout:
                continue
            with conn:
                # Whether the connection inherits the short accept timeout depends on the OS; set it explicitly
                conn.settimeout(2)
                command = conn.recv(1024)
                self.requests.append(command)
                delay, chunks = self._reply(len(self.requests) - 1, command)
                if self._stop.wait(delay):  # Waiting can be cut short by stop()
                    return
                for i, chunk in enumerate(chunks or []):
                    if i > 0 and self._stop.wait(self._chunk_gap):
                        return
                    conn.sendall(chunk)

    def stop(self):
        """Stops the server and frees its port."""
        self._stop.set()
        self._thread.join(timeout=2)
        self._socket.close()


@pytest.fixture
def fake_server() -> Iterator[Callable[..., FakeServer]]:
    """
    Factory for :class:`FakeServer`; every server is stopped after the test.

    :returns: Function that takes the ``reply`` callable of :class:`FakeServer`, or ``chunks`` for a fixed reply.
    """
    servers = []

    def make(reply: Optional[Callable] = None, chunks: Sequence[bytes] = (), delay: float = 0.0,
             chunk_gap: float = 0.0) -> FakeServer:
        """
        :param reply: See :class:`FakeServer`; if given, ``chunks`` and ``delay`` are ignored.
        :param chunks: Fixed reply sent to every connection.
        :param delay: Seconds to wait before the fixed reply.
        :param chunk_gap: Pause between chunks, see :class:`FakeServer`.
        :returns: The running server.
        """
        server = FakeServer(reply or (lambda n, command: (delay, chunks)), chunk_gap)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


class FakeClock:
    """
    Clock for timing tests: time moves only when the code sleeps or a :class:`StubAmmeter` "measures",
    so schedules can be checked exactly and instantly.

    :ivar now_s: Current fake time in seconds.
    :ivar sleeps: Every duration passed to :meth:`sleep`, in order.
    """

    def __init__(self):
        self.now_s = 0.0
        self.sleeps: List[float] = []

    def now(self) -> float:
        """
        :returns: Current fake time in seconds.
        """
        return self.now_s

    def sleep(self, seconds: float) -> None:
        """
        Moves the time forward instead of waiting.

        :param seconds: How long the code wanted to sleep; must not be negative.
        """
        assert seconds >= 0, f"sleep() called with a negative duration {seconds}"
        self.sleeps.append(seconds)
        self.now_s += seconds


class StubAmmeter:
    """
    Ammeter for sampling tests without a network: each measurement takes a given fake time and returns
    a given value or error.

    :ivar name: Ammeter name.
    :ivar calls: Number of measurements taken so far.
    """

    def __init__(self, clock: FakeClock, durations: Sequence[float] = (), errors: Sequence[int] = (),
                 name: str = "stub"):
        """
        :param clock: Fake clock that each measurement moves forward.
        :param durations: Duration of measurement ``i`` in seconds; measurements beyond the list take 0 s.
        :param errors: Indexes of measurements that fail.
        :param name: Ammeter name.
        """
        self.name = name
        self.calls = 0
        self._clock = clock
        self._durations = list(durations)
        self._errors = set(errors)

    def measure(self) -> Measurement:
        """
        :returns: Value ``float(i)`` for the i-th measurement, or a failure for the indexes in ``errors``.
        """
        i = self.calls
        self.calls += 1
        duration = self._durations[i] if i < len(self._durations) else 0.0
        self._clock.now_s += duration
        if i in self._errors:
            return Measurement(self.name, 0.0, None, f"error #{i}", duration)
        return Measurement(self.name, 0.0, float(i), None, duration)


@pytest.fixture
def clock() -> FakeClock:
    """
    :returns: A fresh fake clock starting at 0.
    """
    return FakeClock()
