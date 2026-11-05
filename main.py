import threading
import time
from pathlib import Path

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import AmmeterError, get_current
from src.utils.config import load_config

CONFIG_PATH = Path(__file__).parent / "config" / "config.yaml"

# Maps the ammeter names used in config.yaml to their emulator classes
EMULATORS = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def run_emulator(name: str, port: int):
    """
    Starts one ammeter emulator and serves requests until the program exits.
    If the port cannot be bound, prints a message instead of crashing the thread.

    Args:
        name: Ammeter name as used in config.yaml, a key of EMULATORS (e.g. "greenlee").
        port: TCP port the emulator listens on.
    """
    try:
        EMULATORS[name](port).start_server()
    except OSError as e:
        print(f"[{name}] Cannot start emulator on port {port}: {e}. "
              f"Free the port or change it in {CONFIG_PATH.name}.")


if __name__ == "__main__":
    ammeters = load_config(CONFIG_PATH)["ammeters"]

    # Start each ammeter in a separate thread
    for name, settings in ammeters.items():
        threading.Thread(target=run_emulator, args=(name, settings["port"]), daemon=True).start()

    # Wait for the servers to start
    time.sleep(5)

    for name, settings in ammeters.items():
        try:
            current = get_current(settings["port"], settings["command"].encode("utf-8"))
        except AmmeterError as e:  # unreachable ammeter or invalid reply
            print(f"[{name}] Measurement failed: {e}")
        else:
            print(f"[{name}] Received current measurement from port {settings['port']}: {current} A")
