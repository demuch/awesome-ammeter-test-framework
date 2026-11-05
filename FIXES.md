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

## Known issues not fixed yet

These issues are in the code that the testing framework replaces or wraps; they will be addressed there.

- `src/testing/test_framework.py`: `Dict` is used without being imported, so the module fails to import with `NameError`.
- `examples/run_tests.py`: calls `run_test()` without the required `ammeter_type` argument (README says not to use it).
- `src/utils/logger.py`: the log file path is computed but no handler or level is set, so nothing is written to the file.
- `Ammeters/client.py`: prints the value instead of returning it, so it cannot be used for analysis.
- `Ammeters/base_ammeter.py`: an unknown command gets no reply (the client cannot tell it from a lost response);
  one client is served at a time; a single `recv(1024)` assumes the whole command arrives in one TCP segment.
- `README.md`: file names do not match the repository (`Ammeters/main.py`, `AmmeterTester.py`, `run_test.py`).
- CIRCUTOR: `sum(v * dt)` yields volt-seconds; a real Rogowski coil needs a sensitivity coefficient to get amperes.
