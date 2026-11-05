import threading
from typing import Dict, List

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.ammeter import Ammeter
from src.utils.config import ConfigError

DEFAULT_READY_TIMEOUT_S = 5.0

# Maps the ammeter names used in config.yaml to their emulator classes
EMULATORS = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


class EmulatorStartError(Exception):
    """One or more emulators did not start."""


class _EmulatorThread(threading.Thread):
    """
    Runs one emulator in a background thread and remembers why it stopped, if it did.

    :ivar ammeter: The ammeter this emulator serves.
    :ivar ready: Set when the emulator accepts connections, or when it failed to start.
    :ivar error: The exception that stopped the emulator, or ``None``.
    """

    def __init__(self, ammeter: Ammeter):
        """
        :param ammeter: The ammeter to emulate; its name selects the emulator class, its port is used for listening.
        """
        super().__init__(name=f"emulator-{ammeter.name}", daemon=True)
        self.ammeter = ammeter
        self.ready = threading.Event()
        self.error = None

    def run(self):
        """
        Runs the emulator until the program exits. A startup failure (e.g. port in use) is stored in
        :attr:`error` and :attr:`ready` is set, so the waiting caller does not have to wait for the timeout.
        """
        try:
            EMULATORS[self.ammeter.name](self.ammeter.port).start_server(self.ready)
        except Exception as e:
            self.error = e
            self.ready.set()


def start_emulators(ammeters: Dict[str, Ammeter], timeout: float = DEFAULT_READY_TIMEOUT_S) -> None:
    """
    Starts an emulator for every ammeter and waits until each one accepts connections.
    All emulators are started even if some of them fail, so the others can still be used.

    :param ammeters: Ammeters by name, as returned by :func:`src.testing.ammeter.load_ammeters`.
    :param timeout: Maximum seconds to wait for each emulator to become ready.
    :raises ConfigError: There is no emulator for one of the ammeter names. Nothing is started in that case.
    :raises EmulatorStartError: At least one emulator failed to start or did not become ready in time.
        The message lists all of them.
    """
    unknown = [name for name in ammeters if name not in EMULATORS]
    if unknown:
        raise ConfigError(f"No emulator for ammeter(s) {unknown}; known: {sorted(EMULATORS)}")

    threads = [_EmulatorThread(ammeter) for ammeter in ammeters.values()]
    for thread in threads:
        thread.start()

    failures: List[str] = []
    for thread in threads:
        name, port = thread.ammeter.name, thread.ammeter.port
        if not thread.ready.wait(timeout):
            failures.append(f"'{name}' on port {port}: not ready after {timeout} s")
        elif thread.error is not None:
            failures.append(f"'{name}' on port {port}: {thread.error!r}")
    if failures:
        raise EmulatorStartError("Emulators failed to start: " + "; ".join(failures))
