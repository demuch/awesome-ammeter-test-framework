import sys

from src.testing.ammeter import load_ammeters
from src.utils.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from src.utils.emulators import EmulatorStartError, start_emulators

if __name__ == "__main__":
    try:
        ammeters = load_ammeters(load_config(DEFAULT_CONFIG_PATH))
        # Start each ammeter emulator in a separate thread and wait until all of them accept connections
        start_emulators(ammeters)
    except ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    except EmulatorStartError as e:
        # Keep going: the ammeters that did start can still be measured
        print(f"{e}. Free the port or change it in {DEFAULT_CONFIG_PATH.name}.")

    for ammeter in ammeters.values():
        m = ammeter.measure()
        if m.ok:
            print(f"[{m.ammeter}] Received current measurement from port {ammeter.port}: "
                  f"{m.value} A ({m.duration_s * 1000:.1f} ms)")
        else:
            print(f"[{m.ammeter}] Measurement failed: {m.error}")
