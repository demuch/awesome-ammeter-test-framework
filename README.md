# Ammeter Test Framework

[![tests](https://github.com/demuch/awesome-ammeter-test-framework/actions/workflows/tests.yml/badge.svg)](https://github.com/demuch/awesome-ammeter-test-framework/actions/workflows/tests.yml)

A configuration-driven framework for testing ammeters: it queries every ammeter through one API, takes series of
measurements on a precise schedule, computes statistics, archives every run with its metadata and compares runs.
It works with the three emulated ammeters of the assignment (Greenlee, ENTES, CIRCUTOR) and with any device that
answers a text command over TCP.

- **[DESIGN.md](DESIGN.md)**: architecture and design decisions.
- **[FIXES.md](FIXES.md)**: every defect found in the provided code, how it was reproduced and fixed, and the
  libraries that were installed.
- **[sample_results/](sample_results/)**: archived sample runs.
- **[docs/ORIGINAL_README.md](docs/ORIGINAL_README.md)**: the README of the assignment, unchanged.

## Quick start

Python 3.9 or newer. From the project root:

```sh
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # PyYAML only
```

Get one measurement from each ammeter (the emulators are started automatically):

```sh
python main.py
```
```
[greenlee] Received current measurement from port 5000: 0.1683762350379121 A (0.3 ms)
[entes] Received current measurement from port 5001: 14.433671669929137 A (0.3 ms)
[circutor] Received current measurement from port 5002: 0.014077552128644403 A (0.2 ms)
```

Run the configured test on every ammeter, archive the runs and print a report per ammeter:

```sh
python -m src.run
```
```
2026-11-07 10:13:54,341 [INFO] test_run: Testing greenlee ammeter...
2026-11-07 10:13:56,252 [INFO] test_run: Saved greenlee run as 20261107-081354-greenlee-2a661cf5
...
Results for greenlee:
=== greenlee: 20 measurements, 20 ok, 0 failed (100%) ===
Values (A)     mean 0.1356  median 0.09236  stdev 0.1458  min 0.03723  max 0.6908  relative_spread 107.5%
Response time  mean 0.67 ms  median 0.62 ms  stdev 0.16 ms  min 0.38 ms  max 0.93 ms  relative_spread 23.5%
Timing         10 Hz planned, 9.98 Hz actual; lag mean 2.7 ms, max 5.0 ms; 0 late, schedule shifted by 0.0 ms
               interval between measurements 95.0-105.0 ms
```

Options change a single run without editing the config:

```sh
python -m src.run --ammeter greenlee entes        # only these ammeters
python -m src.run --count 100 --frequency 50      # any two of --count, --duration, --frequency
python -m src.run --no-save                       # do not archive this run
python -m src.run --config other.yaml             # another configuration file
python -m src.run --help
```

Exit codes: `0` every ammeter was tested; `1` a configuration error, an emulator that did not start or a run that
could not be archived; `2` wrong usage. Failed measurements do not change the exit code: they are results of the
test, shown in the report.

List your archived runs, then look at the sample runs that come with the repository (a run ID can be shortened to
any unique beginning):

```sh
python -m src.results list
python -m src.results --dir sample_results list
python -m src.results --dir sample_results show 20261107-081400        # an ammeter that did not answer
python -m src.results --dir sample_results compare 20261107-081348 20261107-081354
```

## What the report means

| Line | Content |
|---|---|
| header | how many measurements were taken, how many succeeded and failed |
| `Values` | statistics of the successful measurements: mean, median, sample standard deviation, min, max, and `relative_spread` = stdev / mean, which compares ammeters with very different scales |
| `Response time` | the same statistics for how long the ammeter took to answer, over all requests (a slow failure is still a slow answer) |
| `Timing` | planned and actual frequency, how late measurements started, how many could not start on time, and how far the schedule was shifted because of them; the shortest and longest interval show local problems that the average frequency hides |
| `Failures` | only when measurements failed: each reason once, with its count |

## Project structure

```
main.py                    Provided; one measurement from each ammeter (fixed, see FIXES.md)
config/config.yaml         All settings: ammeters, sampling, report, archive
examples/run_tests.py      Provided example, kept unchanged: marked "don't use it" (see FIXES.md)
Ammeters/                  Provided emulators and client (fixed, see FIXES.md)
  base_ammeter.py          TCP server shared by all emulators
  *_Ammeter.py             The three emulators
  client.py                get_current(): one request, returns a float or raises a typed error
src/
  testing/
    ammeter.py             Unified API: Ammeter.measure() -> Measurement, load_ammeters()
    sampling.py            SamplingConfig, sample(): series on a schedule with a timing report
    analysis.py            Statistics, TestResult, text report
    archive.py             Run IDs, metadata, saving and loading runs (JSON)
    test_framework.py      AmmeterTestFramework: ties the parts together
  run.py                   Command line: run the test on ammeters (python -m src.run)
  results.py               Command line: list, show, compare archived runs (python -m src.results)
  utils/
    config.py              Loading config.yaml, ConfigError
    emulators.py           Starting emulators and waiting until they accept connections
    logger.py              Provided TestLogger (fixed)
tests/                     pytest suite for the framework itself (see below)
sample_results/            Archived sample runs
.github/workflows/         CI: the test suite on Linux, Windows and macOS
```

## Configuration

Everything is set in `config/config.yaml`. A setting that is missing, of the wrong type or contradicts another
gives a `ConfigError` that names the problem before anything is measured.

### `ammeters`

One entry per ammeter; the key is its name.

| Key | Required | Meaning |
|---|---|---|
| `port` | yes | TCP port, 1-65535 |
| `command` | yes | text the ammeter expects to send one measurement |
| `host` | no | host name or IP address; default `localhost` |
| `timeout` | no | seconds to wait for connecting and for each part of the reply; default `5` |
| `emulator` | no | import path of the emulator class to start for this ammeter, e.g. `Ammeters.Greenlee_Ammeter.GreenleeAmmeter`; without it the ammeter is treated as a real device and only queried |

The configured ammeters use the ports and commands of the assignment:

| Ammeter | Port | Command |
|---|---|---|
| greenlee | 5000 | `MEASURE_GREENLEE -get_measurement` |
| entes | 5001 | `MEASURE_ENTES -get_data` |
| circutor | 5002 | `MEASURE_CIRCUTOR -get_measurement` |

**Adding an ammeter** needs no change to the framework code:

- a real device: add an entry with `host`, `port` and `command`;
- a new emulator: write a subclass of `AmmeterEmulatorBase` (see the three existing ones) and add an entry with
  its import path in `emulator`.

### `testing.sampling`

Set any two of the three values; the third one is computed (`count = duration x frequency`). If all three are set,
they must agree. Measurement `i` starts at `i / frequency` seconds, so 20 measurements at 10 Hz start at
0.0, 0.1, ..., 1.9 s.

| Key | Meaning |
|---|---|
| `measurements_count` | number of measurements |
| `total_duration_seconds` | total test duration |
| `sampling_frequency_hz` | measurements per second |

### `analysis`

| Key | Meaning |
|---|---|
| `statistical_metrics` | which metrics the report shows: any of `mean`, `median`, `stdev`, `min`, `max`, `relative_spread`; empty or missing means all. All metrics are always computed and archived. |
| `visualization` | reserved for plots; not used yet |

### `result_management`

| Key | Meaning |
|---|---|
| `results_dir` | folder for archived runs; relative paths start at the project root; default `results/runs` |
| `save_results` | whether `python -m src.run` archives every run (unless `--no-save`); default `true` |

## Using the framework from Python

```python
from src.testing.test_framework import AmmeterTestFramework
from src.utils.emulators import start_emulators

framework = AmmeterTestFramework()            # reads config/config.yaml
start_emulators(framework.ammeters)           # only needed for emulated ammeters

result = framework.run_test("greenlee")       # one series with the configured sampling
print(result.values.mean, result.values.stdev, result.success_rate)
print(framework.report(result))

record = framework.save(result)               # archive it
print(record.run_id)
```

A failed measurement does not raise: it is kept in the series with its error, so one failure does not stop a test.
`run_test()` also accepts its own `SamplingConfig`, e.g.
`framework.run_test("entes", SamplingConfig.from_values(count=100, frequency_hz=50))`.

## Result archive

Every run is one JSON file in `results/runs/` named after its run ID, e.g. `20261105-185430-greenlee-1a982a4e`:
the UTC start time, the ammeter and a random part, so IDs sort by time and never collide. A file contains:

- the ammeter settings and the sampling settings;
- the environment: Python version, operating system and the git commit of the code, marked `+dirty` if Python
  files had uncommitted changes;
- a summary of all metrics;
- every single measurement with its value or error, timing and duration.

Files are written atomically, so a crash never leaves a broken run file. Unreadable files are skipped by `list` with
a warning. When a run is loaded, its metrics are recomputed from the raw measurements.

```sh
python -m src.results list [--ammeter NAME]       # all runs, newest first
python -m src.results show RUN_ID                 # metadata and full report of one run
python -m src.results compare RUN_ID RUN_ID ...   # metrics side by side, change of the last run vs the first
python -m src.results --dir FOLDER ...            # another archive folder
```

`compare` shows the change in percent, and for shares (success rate, relative spread) in percentage points.
Exit codes: `0` success, `1` a run or the archive cannot be read, `2` wrong usage.

## Tests of the framework

### Two kinds of testing in this project

- **Testing ammeters** is what the framework *does*: `python -m src.run` samples each ammeter, computes
  statistics and archives the results. The ammeters (here: the emulators) are the system under test.
- **Testing the framework** is what `tests/` *does*: the pytest suite checks that the framework itself works
  correctly: that it talks to an ammeter correctly, keeps its schedule, computes the statistics right, stores
  results without loss and reports errors clearly. **These tests do not evaluate the ammeters or their
  measurements.**

Results of testing ammeters can only be trusted if the tool that produces them is tested itself: a framework that
drifts from its schedule or loses data when saving would make every conclusion about the ammeters wrong.

The emulators and fake servers in the tests are **stand-in ammeters**, not the object of the tests. They let the
tests show how the framework handles valid replies, garbage, silence, error replies and slow replies.

`tests/test_emulators.py` is the one file that runs code of the provided emulators directly. It does not assess the
ammeters either: it contains regression tests for the fixes made to the provided emulator code (FIXES.md, Fix 1-6),
and it checks that the emulators behave as `docs/ORIGINAL_README.md` describes, because the framework relies on that.

### Running the tests

```sh
pip install -r requirements-dev.txt          # adds pytest and pytest-cov; not needed to use the framework
pytest                                       # all tests, a few seconds
pytest -m "not integration"                  # only the fast unit tests, without sockets
pytest --cov=src --cov=Ammeters --cov-report=term-missing   # with line coverage
```

| File | What is checked |
|---|---|
| `test_client.py` | valid replies, replies in several TCP parts, every kind of invalid reply, refused connection, timeout |
| `test_ammeter.py` | `Ammeter.measure()` turns ammeter failures into failed measurements but does not hide framework bugs; `TestLogger` |
| `test_sampling.py` | the count/duration/frequency rules; exact schedule, no drift, late measurements and schedule shift without a burst |
| `test_analysis.py` | statistics on data with known results and edge cases; the report |
| `test_archive.py` | saving and loading without loss (`loaded == saved`), run IDs, crash while writing, broken files, code version |
| `test_run_cli.py` | `python -m src.run`: all or selected ammeters, sampling options, `--no-save`, errors and exit codes |
| `test_results_cli.py` | `list`, `show`, `compare` output and exit codes |
| `test_config.py` | `config.yaml` matches the assignment; every invalid setting; loading and starting emulators |
| `test_emulators.py` | regression tests for the fixes in the provided emulators; emulator behaviour as documented |
| `test_end_to_end.py` | the whole path from a config to the archive; `sample_results/` stays readable by the current code |

How the suite stays fast and reliable:

- **No fixed sleeps.** Timing is tested with a fake clock passed to `sample()`, so a series of several seconds is
  checked exactly and instantly; one test uses the real clock with a tolerance.
- **Free ports from the operating system**, so tests never clash with each other or with a running `main.py`.
- **Independent tests**: each test prepares its own ports, folders and data.
- **Strict settings** (`pytest.ini`): any warning fails the run, unknown markers are errors.
- **Mutation checks**: for the key tests the fixed code was broken on purpose to confirm that the test fails.

### Continuous integration

GitHub Actions runs the whole suite with coverage, `main.py` and `python -m src.run` on Linux, Windows and
macOS with Python 3.9 and 3.14 on every push (`.github/workflows/tests.yml`).

## Platform notes

- **macOS:** port 5000 is used by the AirPlay Receiver. The Greenlee emulator still starts there because it binds
  `127.0.0.1` with `SO_REUSEADDR`; if the port is busy on another system, change it in `config.yaml`.
- **Timing precision depends on the operating system.** Measurements wait with `time.sleep()`, and how late the
  system wakes the program up differs a lot. Measured lag of measurement starts (the test runner,
  20 measurements at 10 Hz) in CI and on a development machine:

  | Platform | Mean lag | Max lag |
  |---|---|---|
  | Linux, Python 3.9 and 3.14 (CI) | 0.1-0.2 ms | 0.2 ms |
  | Windows, Python 3.14 (CI) | 0.3-0.4 ms | 0.6 ms |
  | Windows, Python 3.9 (CI) | 3.5-5.2 ms | 15.5 ms |
  | macOS, development Mac | about 3 ms | about 5 ms |
  | macOS, CI virtual machine | 29-46 ms | 76 ms |

  The lag does not add up over a series (see DESIGN.md), and every report shows it, so a run on a slow platform is
  recognisable. Windows is precise from Python 3.11 on, which uses high-resolution timers there.
- **Windows:** connecting to a port where nothing listens takes about 2 s instead of failing at once (found by CI),
  so each measurement of an unreachable ammeter takes about 2 s and its series falls behind schedule.

## Requirements

- Python 3.9 or newer, any operating system.
- To use the framework: **PyYAML** (`requirements.txt`). Everything else is the Python standard library.
- To run the tests: **pytest** and **pytest-cov** (`requirements-dev.txt`).
