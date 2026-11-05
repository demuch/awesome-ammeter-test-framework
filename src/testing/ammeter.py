import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from Ammeters.client import AmmeterError, get_current
from src.utils.config import ConfigError

DEFAULT_HOST = 'localhost'
DEFAULT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Measurement:
    """
    One measurement in the same format for every ammeter type.

    :ivar ammeter: Name of the ammeter that was queried, e.g. ``"greenlee"``.
    :ivar timestamp: Unix time when the request started.
    :ivar value: Measured current, or ``None`` if the measurement failed.
    :ivar error: Why the measurement failed, or ``None`` on success.
    :ivar duration_s: How long the request took, in seconds.
    """
    ammeter: str
    timestamp: float
    value: Optional[float]
    error: Optional[str]
    duration_s: float

    @property
    def ok(self) -> bool:
        """
        :returns: ``True`` if the measurement succeeded.
        """
        return self.error is None


@dataclass(frozen=True)
class Ammeter:
    """
    One ammeter as the framework sees it: all ammeter types are used the same way via :meth:`measure`.

    :ivar name: Ammeter name as used in config.yaml, e.g. ``"greenlee"``.
    :ivar port: TCP port of the ammeter.
    :ivar command: Command that requests a measurement.
    :ivar host: Host name or IP address of the ammeter.
    :ivar timeout: Seconds to wait for connecting and for each chunk of the reply.
    """
    name: str
    port: int
    command: bytes
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT_S

    def measure(self) -> Measurement:
        """
        Requests one measurement. A failure of the ammeter does not raise: it is returned as a
        :class:`Measurement` with ``value=None`` and the reason in ``error``, so one failure does not
        stop a series of measurements. Errors in the framework itself are not caught.

        :returns: The measurement, successful or not.
        """
        timestamp = time.time()
        started = time.perf_counter()  # Monotonic clock, not affected by system clock changes
        try:
            value = get_current(self.port, self.command, self.timeout, self.host)
            error = None
        except AmmeterError as e:
            value = None
            error = str(e)
        duration_s = time.perf_counter() - started
        return Measurement(self.name, timestamp, value, error, duration_s)


def load_ammeters(config: Dict) -> Dict[str, Ammeter]:
    """
    Creates the ammeters described in the ``ammeters`` section of the configuration.

    :param config: Configuration as returned by :func:`src.utils.config.load_config`.
    :returns: Ammeters by name, in the order of the configuration file.
    :raises ConfigError: The section is missing or empty, an ammeter has invalid settings,
        or two ammeters use the same host and port.
    """
    section = config.get("ammeters")
    if not isinstance(section, dict) or not section:
        raise ConfigError("The 'ammeters' section is missing or empty")

    ammeters = {name: _ammeter_from_settings(name, settings) for name, settings in section.items()}

    seen = {}
    for ammeter in ammeters.values():
        address = (ammeter.host, ammeter.port)
        if address in seen:
            raise ConfigError(f"Ammeters '{seen[address]}' and '{ammeter.name}' both use {ammeter.host}:{ammeter.port}")
        seen[address] = ammeter.name
    return ammeters


def _ammeter_from_settings(name: str, settings: Any) -> Ammeter:
    """
    Validates the settings of one ammeter and creates it.

    :param name: Ammeter name, the key in the ``ammeters`` section.
    :param settings: Value of that key: a mapping with ``port``, ``command`` and optionally ``host`` and ``timeout``.
    :returns: The ammeter.
    :raises ConfigError: A required setting is missing or a setting has an invalid value.
    """
    if not isinstance(settings, dict):
        raise ConfigError(f"Ammeter '{name}': settings must be a mapping with 'port' and 'command'")
    for key in ("port", "command"):
        if key not in settings:
            raise ConfigError(f"Ammeter '{name}': missing '{key}'")

    port = settings["port"]
    # bool is a subclass of int in Python, so 'port: true' would otherwise pass as port 1
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError(f"Ammeter '{name}': 'port' must be an integer from 1 to 65535, got {port!r}")

    command = settings["command"]
    if not isinstance(command, str) or not command.strip():
        raise ConfigError(f"Ammeter '{name}': 'command' must be a non-empty string, got {command!r}")

    host = settings.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or not host.strip():
        raise ConfigError(f"Ammeter '{name}': 'host' must be a non-empty string, got {host!r}")

    timeout = settings.get("timeout", DEFAULT_TIMEOUT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError(f"Ammeter '{name}': 'timeout' must be a positive number of seconds, got {timeout!r}")

    return Ammeter(name, port, command.encode('utf-8'), host, float(timeout))
