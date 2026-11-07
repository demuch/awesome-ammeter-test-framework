import importlib
import inspect
import threading
from typing import Dict, List, Type

from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.testing.ammeter import Ammeter
from src.utils.config import ConfigError

DEFAULT_READY_TIMEOUT_S = 5.0


class EmulatorStartError(Exception):
    """One or more emulators did not start."""


def load_emulator_class(import_path: str) -> Type[AmmeterEmulatorBase]:
    """
    Loads an emulator class by its import path, so a new emulator needs only its class file
    and an entry in config.yaml, not a code change in the framework.

    :param import_path: Module path and class name separated by a dot,
        e.g. ``"Ammeters.Greenlee_Ammeter.GreenleeAmmeter"``.
    :returns: The emulator class.
    :raises ConfigError: The module cannot be imported, has no such class, or the class is not
        a concrete subclass of :class:`AmmeterEmulatorBase`.
    """
    module_name, _, class_name = import_path.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ConfigError(f"Cannot load emulator {import_path!r}: {e}") from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ConfigError(f"Cannot load emulator {import_path!r}: module {module_name!r} has no {class_name!r}")
    if not (isinstance(cls, type) and issubclass(cls, AmmeterEmulatorBase)):
        raise ConfigError(f"Emulator {import_path!r} is not a subclass of AmmeterEmulatorBase")
    if inspect.isabstract(cls):
        raise ConfigError(f"Emulator {import_path!r} is abstract and cannot be started")
    return cls


class _EmulatorThread(threading.Thread):
    """
    Runs one emulator in a background thread and remembers why it stopped, if it did.

    :ivar ammeter: The ammeter this emulator serves.
    :ivar ready: Set when the emulator accepts connections, or when it failed to start.
    :ivar error: The exception that stopped the emulator, or ``None``.
    """

    def __init__(self, ammeter: Ammeter, emulator_class: Type[AmmeterEmulatorBase]):
        """
        :param ammeter: The ammeter to emulate; its port is used for listening.
        :param emulator_class: The emulator class to run.
        """
        super().__init__(name=f"emulator-{ammeter.name}", daemon=True)
        self.ammeter = ammeter
        self.emulator_class = emulator_class
        self.ready = threading.Event()
        self.error = None

    def run(self):
        """
        Runs the emulator until the program exits. A startup failure (e.g. port in use) is stored in
        :attr:`error` and :attr:`ready` is set, so the waiting caller does not have to wait for the timeout.
        """
        try:
            errors = self.ammeter.simulate_errors
            # Passed only when set, so emulator classes with their own __init__(port) keep working
            emulator = self.emulator_class(self.ammeter.port, errors) if errors else self.emulator_class(self.ammeter.port)
            emulator.start_server(self.ready)
        except Exception as e:
            self.error = e
            self.ready.set()


def start_emulators(ammeters: Dict[str, Ammeter], timeout: float = DEFAULT_READY_TIMEOUT_S) -> None:
    """
    Starts an emulator for every ammeter that has one configured and waits until each one accepts
    connections. Ammeters without ``emulator`` are real devices and are skipped.
    All emulators are started even if some of them fail, so the others can still be used.

    :param ammeters: Ammeters by name, as returned by :func:`src.testing.ammeter.load_ammeters`.
    :param timeout: Maximum seconds to wait for each emulator to become ready.
    :raises ConfigError: An emulator class cannot be loaded. All classes are checked before
        anything is started, so nothing is started in that case.
    :raises EmulatorStartError: At least one emulator failed to start or did not become ready in time.
        The message lists all of them.
    """
    emulated = [ammeter for ammeter in ammeters.values() if ammeter.emulator is not None]
    threads = [_EmulatorThread(ammeter, load_emulator_class(ammeter.emulator)) for ammeter in emulated]
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
