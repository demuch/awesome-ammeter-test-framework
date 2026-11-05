# Fixes to the Provided Code

This document lists every defect found in the provided ammeter infrastructure, how it was reproduced, and how it was fixed.
Each fix is a separate commit, so `git log` shows the history step by step.

## Environment

- Python 3.9.6 (macOS), virtual environment in `.venv`
- Installed library: **PyYAML 6.0.3** (`pip install -r requirements.txt`)

Before installation `import yaml` failed with `ModuleNotFoundError`, so the config loader could not run.

**`requirements.txt` was reduced to PyYAML only.** The original file listed numpy, scipy, matplotlib, seaborn, PyYAML
and pandas, but a scan of all imports showed that the code uses only `yaml`; everything else is the standard library.
The spec asks to minimize external dependencies, so the unused packages were removed. `main.py` was verified in a fresh
virtual environment with PyYAML as the only installed package. Statistics, run IDs and result storage will use the
standard library (`statistics`, `uuid`, `json`); matplotlib will be added later as an optional dependency for
visualization only.

## Fix 1: Truncated commands in `main.py`

**Symptom:** after uncommenting the requests in `main.py`, all three requests printed `No data received.`

**Root cause:** `AmmeterEmulatorBase.start_server()` compares the received bytes with the expected command exactly
(`data == self.get_current_command`). `main.py` sent truncated commands such as `b'MEASURE_GREENLEE'`
instead of `b'MEASURE_GREENLEE -get_measurement'`. On a mismatch the server closes the connection without a reply,
so `recv()` on the client returns empty bytes.

**Fix:** send the full commands specified in `README.md`.

## Fix 2: CIRCUTOR command mismatch

**Symptom:** with the README command, CIRCUTOR still returned `No data received.`

**Root cause:** `Circutor_Ammeter.py` expected `MEASURE_CIRCUTOR -get_measurement -current`, while `README.md` and
`config.yaml` both specify `MEASURE_CIRCUTOR -get_measurement`.

**Fix:** the emulator was aligned with the documentation, not the other way round, because two sources (README and config)
agree, and the other two ammeters follow the same `MEASURE_<TYPE> -<action>` pattern without a third flag.
In a real project this would be clarified with the requirements owner.

## Fix 3: `Address already in use` on restart

**Symptom:** running `main.py` again within about a minute crashed every emulator thread with
`OSError: [Errno 48] Address already in use`, and the client then got `ConnectionRefusedError`.
The comment in `main.py` suggested increasing the sleep time, which only hides the problem.

**Root cause:** after the server closes a TCP connection, the OS keeps the port in the `TIME_WAIT` state.
Without `SO_REUSEADDR`, `bind()` is rejected during that period.

**Fix:** `s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)` before `bind()` in `base_ammeter.py`.
Verified by running `main.py` three times back to back.

## Fix 4: Ports differ from README and are hardcoded

**Symptom:** `main.py` used ports 5001/5002/5003, while `README.md` specifies 5000/5001/5002.
Server and client inside `main.py` used the same wrong numbers, so this did not break the connection,
but it did not conform to the spec.

**Fix:** ports and commands were moved to the `ammeters` section of `config/config.yaml` (the commented-out section
already contained the README values). `main.py` now reads them from the config, so changing a port does not require
a code change.

**macOS note:** port 5000 is used by the AirPlay Receiver (`ControlCenter` process, macOS 12+), which listens on `*:5000`.
Without `SO_REUSEADDR` the Greenlee emulator cannot bind port 5000 on macOS. With it, macOS allows binding the more
specific `127.0.0.1:5000`, so the emulator works. This is BSD-specific behaviour; if the port is still busy on another
system, change it in `config.yaml` or turn off AirPlay Receiver (System Settings → General → AirDrop & Handoff).

## Fix 5: Error handling for unavailable emulators

**Symptom (negative test):** with port 5001 held by an unrelated process that never answers, the client blocked on
`recv()` until that process exited, and then `main.py` crashed with `ConnectionResetError`; CIRCUTOR was never queried.

**Root cause:** the client socket had no timeout, and nothing handled network errors.

**Fix:**
- `request_current_from_ammeter()` got a `timeout` parameter (default 5 s, backwards compatible).
- `main.py` reports a port that cannot be bound, connection refused, timeout and reset with a clear message per ammeter
  and continues with the remaining ammeters.

## Fix 6: Server swallows unknown commands and dies on client errors

**Symptom 1:** a wrong command produced only `No data received.` on the client. The client could not tell
"unknown command" from "device hung" or "reply lost", which is why Fix 1 was hard to diagnose.

**Symptom 2 (negative test):** a client that sent a valid command and then aborted the connection (TCP RST) made
`sendall()` raise `BrokenPipeError`. The exception escaped the `while True` loop and killed the emulator thread;
every following request got `ConnectionRefusedError` until restart. One misbehaving client took the device down.

**Fix (`base_ammeter.py`):**
- An unknown command is answered with `ERROR: unknown command <received bytes>` (truncated to 100 bytes) and logged on
  the server side, so the client can tell a wrong command from a lost reply.
- Handling of one request moved to `_handle_request()`; any exception there is logged and the server keeps serving.
- A connection closed without a command is ignored instead of being treated as an unknown command.

**Fix (`client.py`):** a reply that starts with `ERROR` is reported as an error, not as a current value.

**Verified:** wrong command → explicit error; aborted client → logged, server stays up; empty connection → ignored;
a valid request afterwards succeeds; `main.py` happy path unchanged.

## Fix 7: `Dict` used without import in `test_framework.py`

**Symptom:** `import src.testing.test_framework` failed with `NameError: name 'Dict' is not defined`.

**Root cause:** the return annotation `-> Dict` is evaluated when the function is defined, i.e. when the module is
imported. `Dict` comes from the `typing` module, which was not imported, so the whole module was unusable.

**Fix:** `from typing import Dict`.

## Fix 8: `TestLogger` writes nothing

**Symptom:** after `info()`, `debug()` and `error()` the log directory stayed empty; only the error message reached
the console, without a timestamp.

**Root cause:** `_setup_logger()` computed the log file path but never used it: no handler and no level were set, so
Python fell back to its default behaviour (WARNING and above to the console only).

**Fix:**
- File handler (DEBUG and above) with the computed file name, console handler (INFO and above), timestamped format.
- Handlers left by a previous `TestLogger` with the same name are removed: `logging.getLogger()` returns the same object
  for the same name, so otherwise every line would be written twice.
- `propagate = False`, so messages are not printed again by the root logger.
- The log directory is resolved from the project root, not from the current directory.

**Verified:** run from another directory; console shows INFO/ERROR with timestamps, the file contains all levels,
a second logger with the same name does not duplicate lines.

## Fix 9: Client prints the value instead of returning it

**Problem:** `request_current_from_ammeter()` printed the measurement and returned nothing, and also only printed errors,
so measurements could not be collected or analysed. It also read the reply with a single `recv(1024)`, while TCP may
deliver it in several chunks.

**Fix:** new `get_current()` in `Ammeters/client.py`:
- returns the measurement as `float`;
- reads the reply until the server closes the connection;
- raises `AmmeterConnectionError` (refused, timeout, reset) or `AmmeterResponseError` (`ERROR` reply, empty reply,
  not a number, `nan`/`inf`); both inherit from `AmmeterError`, so callers can catch all of them at once.

`request_current_from_ammeter()` is kept for backwards compatibility and now uses `get_current()`.
`main.py` uses `get_current()` directly.

**Verified:** valid command, wrong command, closed port, silent server (timeout), non-numeric reply, `nan` reply,
empty reply and a reply split into two TCP chunks all behave as expected.

## Fix 10: Default config path depends on the current directory

**Symptom:** `AmmeterTestFramework()` looked for `"config/config.yaml"` relative to the current directory, so it failed
with `FileNotFoundError` when started from any other directory.

**Fix:** the default path is resolved from the project root (`DEFAULT_CONFIG_PATH` in `src/utils/config.py`).
`load_config()` now also raises a clear `ConfigError` for a missing file, invalid YAML or a non-mapping top level.

**Verified:** the framework loads the config when started from `/tmp`; a missing file gives a `ConfigError`.

## Fix 11: `examples/run_tests.py` does not run

**Symptoms:**
- `python examples/run_tests.py` failed with `ModuleNotFoundError: No module named 'src'`: Python looks for modules
  in the script's directory (`examples/`), not in the project root.
- `python -m examples.run_tests` failed with `TypeError: run_test() missing 1 required positional argument`.

Once these were fixed, three more problems would have followed: the emulators were never started, the ammeter list
was hardcoded instead of taken from the config, and the results were never printed.

**Fix:** the project root is added to `sys.path` at the top of the script; the script starts the emulators,
runs `run_test()` for every ammeter in `config.yaml` and prints a report for each. The structure of the original
script (`main()`, one loop to run, one loop to print) is kept.

**Verified:** works from the project root and from another directory; prints three reports.

## Other changes to the provided code

These are not bug fixes, but they change code that came with the assignment:

- **Emulators log instead of printing** (`base_ammeter.py`, `*_Ammeter.py`). Each request printed 2-3 lines, which
  buried the test report in noise. Per-request details are now `DEBUG`, server start is `INFO` (both hidden by
  default), unknown commands and failed requests are `WARNING` (always shown). Message texts are unchanged.
- **`start_server()` takes an optional `ready` event**, set right after `listen()`, so callers wait until the
  emulator accepts connections instead of sleeping a fixed 5 seconds. Calling it without arguments works as before.

## Known issues not fixed yet

These issues are in the code that the testing framework replaces or wraps; they will be addressed there.

- `Ammeters/base_ammeter.py`: one client is served at a time; a single `recv(1024)` assumes the whole command arrives
  in one TCP segment.
- `README.md`: file names do not match the repository (`Ammeters/main.py`, `AmmeterTester.py`, `run_test.py`).