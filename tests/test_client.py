"""Tests of Ammeters/client.py: getting one measurement and every kind of bad reply."""
import pytest

from Ammeters.client import (AmmeterConnectionError, AmmeterError, AmmeterResponseError, get_current,
                             request_current_from_ammeter)
from tests.conftest import free_port

pytestmark = pytest.mark.integration  # Every test here talks to a real socket


def test_valid_reply_is_returned_as_float(fake_server):
    """A numeric reply is returned as a float, not printed."""
    server = fake_server(chunks=[b"12.5"])
    assert get_current(server.port, b"CMD") == 12.5


def test_command_is_sent_unchanged(fake_server):
    """The command reaches the server byte for byte."""
    server = fake_server(chunks=[b"1.0"])
    get_current(server.port, b"MEASURE_GREENLEE -get_measurement")
    assert server.requests == [b"MEASURE_GREENLEE -get_measurement"]


def test_reply_split_into_chunks_is_joined(fake_server):
    """TCP may deliver the reply in parts; the client reads until the server closes the connection."""
    # The pause makes the parts arrive separately; without it TCP may join them and the test would prove nothing
    server = fake_server(chunks=[b"12.", b"5"], chunk_gap=0.2)
    assert get_current(server.port, b"CMD") == 12.5


@pytest.mark.parametrize("reply, message", [
    (b"ERROR: unknown command b'X'", "ERROR: unknown command"),
    (b"", "empty reply"),
    (b"abc", "not a number"),
    (b"\xff\xfe", "not a number"),
    (b"nan", "not a finite number"),
    (b"inf", "not a finite number"),
    (b"-inf", "not a finite number"),
])
def test_invalid_reply_raises_response_error(fake_server, reply, message):
    """A reply that is not a finite number is an AmmeterResponseError with the reason."""
    server = fake_server(chunks=[reply] if reply else [])
    with pytest.raises(AmmeterResponseError, match=message):
        get_current(server.port, b"CMD")


def test_nothing_listening_raises_connection_error():
    """A closed port is an AmmeterConnectionError, not a raw ConnectionRefusedError."""
    with pytest.raises(AmmeterConnectionError, match="ConnectionRefusedError"):
        get_current(free_port(), b"CMD")


def test_silent_server_raises_connection_error_after_timeout(fake_server):
    """A server that never answers does not hang the client: the timeout ends the request."""
    server = fake_server(chunks=[b"1.0"], delay=5)
    with pytest.raises(AmmeterConnectionError, match="timed out"):
        get_current(server.port, b"CMD", timeout=0.2)


def test_both_errors_share_one_base_class():
    """Callers can catch every client error with AmmeterError."""
    assert issubclass(AmmeterConnectionError, AmmeterError)
    assert issubclass(AmmeterResponseError, AmmeterError)


def test_request_current_from_ammeter_prints_value(fake_server, capsys):
    """The old print-only function still works for backwards compatibility."""
    server = fake_server(chunks=[b"3.25"])
    request_current_from_ammeter(server.port, b"CMD")
    assert f"from port {server.port}: 3.25 A" in capsys.readouterr().out


def test_request_current_from_ammeter_prints_invalid_reply(fake_server, capsys):
    """An invalid reply is printed, not raised, as before."""
    server = fake_server(chunks=[b"ERROR: unknown command"])
    request_current_from_ammeter(server.port, b"CMD")
    assert "returned an invalid reply" in capsys.readouterr().out
