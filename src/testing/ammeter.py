import time
from dataclasses import dataclass
from typing import Optional

from Ammeters.client import AmmeterError, get_current

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
