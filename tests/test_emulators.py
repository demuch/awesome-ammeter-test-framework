"""Tests of the provided emulators: replies, robustness, and values against the ranges in README.md."""
import socket
import struct
import sys

import pytest

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import AmmeterResponseError, get_current
from src.utils.config import DEFAULT_CONFIG_PATH, load_config
from src.utils.emulators import start_emulators
from src.testing.ammeter import Ammeter
from tests.conftest import EMULATORS, free_port

# The emulators listen on IPv4 only. "localhost" resolves to IPv6 (::1) first on Windows, where the refused
# IPv6 attempt costs about 2 seconds before IPv4 is tried; the framework's client uses IPv4 directly as well
LOCAL_IPV4 = "127.0.0.1"


# Lowest and highest possible value from the input ranges in README.md:
# Greenlee 1..10 / 0.1..100; ENTES 0.01..0.1 x 500..2000; CIRCUTOR sum of 10 x 0.1..1.0 x 0.001..0.01
@pytest.mark.parametrize("emulator_class, low, high", [
    (GreenleeAmmeter, 1.0 / 100.0, 10.0 / 0.1),
    (EntesAmmeter, 0.01 * 500, 0.1 * 2000),
    (CircutorAmmeter, 10 * 0.1 * 0.001, 10 * 1.0 * 0.01),
])
def test_values_stay_in_range_from_readme(emulator_class, low, high):
    """1000 values of each emulator lie in the range that follows from the input ranges in README.md."""
    emulator = emulator_class(port=0)  # The port is not used: measure_current() works without a server
    values = [emulator.measure_current() for _ in range(1000)]
    assert all(low <= v <= high for v in values), f"out of [{low}, {high}]: {[v for v in values if not low <= v <= high][:5]}"


@pytest.mark.parametrize("name", sorted(EMULATORS))
def test_emulator_command_matches_config(name):
    """Each emulator expects exactly the command that config.yaml (and README.md) specifies."""
    configured = load_config(DEFAULT_CONFIG_PATH)["ammeters"][name]["command"].encode("utf-8")
    emulator_class = {"greenlee": GreenleeAmmeter, "entes": EntesAmmeter, "circutor": CircutorAmmeter}[name]
    assert emulator_class(port=0).get_current_command == configured


def _send_raw(port: int, data: bytes) -> bytes:
    """
    Sends bytes and reads the whole reply, without any checks of the client.

    :param port: Port of the server.
    :param data: Bytes to send.
    :returns: Everything the server sent before closing the connection.
    """
    with socket.create_connection((LOCAL_IPV4, port), timeout=2) as s:
        s.sendall(data)
        reply = b""
        while True:
            chunk = s.recv(1024)
            if not chunk:
                return reply
            reply += chunk


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(EMULATORS))
def test_valid_command_returns_a_number(emulator, name):
    """Every emulator answers its command with a number."""
    ammeter = emulator(name)
    assert isinstance(get_current(ammeter.port, ammeter.command), float)


@pytest.mark.integration
def test_unknown_command_gets_error_reply(emulator):
    """A wrong command is answered with ERROR instead of a silent close (FIXES.md, Fix 6)."""
    ammeter = emulator("greenlee")
    assert _send_raw(ammeter.port, b"MEASURE_GREENLEE").startswith(b"ERROR: unknown command")
    with pytest.raises(AmmeterResponseError, match="unknown command"):
        get_current(ammeter.port, b"MEASURE_GREENLEE")


@pytest.mark.integration
def test_server_survives_client_that_aborts(emulator):
    """A client that resets the connection before the reply does not stop the server (FIXES.md, Fix 6)."""
    ammeter = emulator("greenlee")
    s = socket.create_connection((LOCAL_IPV4, ammeter.port))
    # Linger with timeout 0 makes close() send a reset; Windows uses two shorts, other systems two ints
    linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    s.sendall(ammeter.command)
    s.close()
    assert isinstance(get_current(ammeter.port, ammeter.command), float)


@pytest.mark.integration
def test_server_ignores_connection_without_command(emulator):
    """A client that connects and closes without sending anything does not break the server."""
    ammeter = emulator("entes")
    socket.create_connection((LOCAL_IPV4, ammeter.port)).close()
    assert isinstance(get_current(ammeter.port, ammeter.command), float)


@pytest.mark.integration
def test_emulator_restarts_on_port_in_time_wait():
    """An emulator can start on a port that still has connections in TIME_WAIT (FIXES.md, Fix 3)."""
    port = free_port()
    # A connection closed by the server side leaves the server's port in TIME_WAIT. The server stands for
    # a previous run of an emulator, so it uses SO_REUSEADDR as well: Linux lets a port in TIME_WAIT be
    # reused only if both the old and the new socket set it
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("localhost", port))
        server.listen()
        client = socket.create_connection((LOCAL_IPV4, port))
        conn, _ = server.accept()
        conn.close()
        client.close()

    # Precondition: without SO_REUSEADDR the port is really blocked, otherwise this test proves nothing
    probe = socket.socket()
    try:
        probe.bind(("localhost", port))
        pytest.skip("this OS does not block bind() during TIME_WAIT")
    except OSError:
        pass
    finally:
        probe.close()

    class_path, command = EMULATORS["greenlee"]
    ammeter = Ammeter("greenlee", port, command, emulator=class_path)
    start_emulators({"greenlee": ammeter})
    assert isinstance(get_current(port, command), float)
