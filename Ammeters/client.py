import math
from socket import socket, AF_INET, SOCK_STREAM

from Ammeters.base_ammeter import ERROR_PREFIX


class AmmeterError(Exception):
    """Base class for all errors raised while requesting a measurement."""


class AmmeterConnectionError(AmmeterError):
    """The ammeter could not be reached: connection refused, timeout or reset."""


class AmmeterResponseError(AmmeterError):
    """The ammeter answered, but the reply is not a valid measurement."""


def get_current(port: int, command: bytes, timeout: float = 5.0, host: str = 'localhost') -> float:
    """
    Requests one current measurement from an ammeter and returns it.

    Args:
        port: TCP port of the ammeter.
        command: Command that requests a measurement, e.g. b'MEASURE_GREENLEE -get_measurement'.
        timeout: Seconds to wait for connecting and for each chunk of the reply.
        host: Host name or IP address of the ammeter.

    Returns:
        The measured current in amperes.

    Raises:
        AmmeterConnectionError: The ammeter cannot be reached (connection refused, timeout, reset).
        AmmeterResponseError: The reply is an ERROR reply, empty, not a number, or nan/inf.
    """
    try:
        with socket(AF_INET, SOCK_STREAM) as s:
            # Without a timeout recv() blocks forever if the peer never answers
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(command)
            # TCP may deliver the reply in several chunks; the server closes the connection when done
            chunks = []
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as e:  # refused, timeout, reset, ...
        raise AmmeterConnectionError(f"{host}:{port}: {e!r}") from e

    data = b''.join(chunks)
    if not data:
        raise AmmeterResponseError(f"{host}:{port}: empty reply to {command!r}")
    if data.startswith(ERROR_PREFIX):
        raise AmmeterResponseError(f"{host}:{port}: {data.decode('utf-8', errors='replace')}")

    try:
        current = float(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as e:
        raise AmmeterResponseError(f"{host}:{port}: reply is not a number: {data[:100]!r}") from e
    # float() accepts 'nan' and 'inf', which would silently break the statistics
    if not math.isfinite(current):
        raise AmmeterResponseError(f"{host}:{port}: reply is not a finite number: {data[:100]!r}")
    return current


def request_current_from_ammeter(port: int, command: bytes, timeout: float = 5.0):
    """
    Requests one measurement and prints it. Kept for backwards compatibility;
    use get_current() when the value is needed.

    Args:
        port: TCP port of the ammeter.
        command: Command that requests a measurement, e.g. b'MEASURE_GREENLEE -get_measurement'.
        timeout: Seconds to wait for connecting and for each chunk of the reply.

    Raises:
        AmmeterConnectionError: The ammeter cannot be reached. An invalid reply is printed, not raised.
    """
    try:
        current = get_current(port, command, timeout)
    except AmmeterResponseError as e:
        print(f"Ammeter on port {port} returned an invalid reply: {e}")
    else:
        print(f"Received current measurement from port {port}: {current} A")
