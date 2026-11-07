"""
Run the configured test on ammeters, archive the runs and print a report per ammeter.

Usage (from the project root)::

    python -m src.run [--ammeter NAME ...] [--count N] [--duration SECONDS] [--frequency HZ] [--no-save] [--config PATH]

Progress is logged to the console and to a file in ``results/logs``; the reports are printed to standard output.
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

from src.testing.archive import ArchiveError
from src.testing.plots import PlotError, plot_run
from src.testing.sampling import COUNT_KEY, DURATION_KEY, FREQUENCY_KEY, SamplingConfig
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import DEFAULT_CONFIG_PATH, ConfigError
from src.utils.emulators import EmulatorStartError, start_emulators
from src.utils.logger import TestLogger


def main(argv: Optional[List[str]] = None) -> int:
    """
    Tests the selected ammeters one after another.

    :param argv: Command-line arguments without the program name; by default ``sys.argv[1:]``.
    Archived runs also get a plot when ``analysis.visualization.enabled`` is true and matplotlib is installed.

    :returns: Exit code: 0 if every ammeter was tested (and archived, if saving is on); 1 for a configuration
        error, an emulator that did not start or a run that could not be archived. Failed measurements are
        results of the test, not errors of the run, so they do not change the exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m src.run",
                                     description="Run the configured test on ammeters and archive the runs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help="configuration file (default: config/config.yaml in the project)")
    # nargs="+" with "extend" accepts both "--ammeter a b" and "--ammeter a --ammeter b"
    parser.add_argument("--ammeter", nargs="+", action="extend", metavar="NAME",
                        help="test only these ammeters (default: every ammeter in the config)")
    sampling = parser.add_argument_group(
        "sampling", "give any two of these to replace testing.sampling from the config for this run")
    sampling.add_argument("--count", type=int, help="number of measurements")
    sampling.add_argument("--duration", type=float, metavar="SECONDS", help="total test duration")
    sampling.add_argument("--frequency", type=float, metavar="HZ", help="measurements per second")
    parser.add_argument("--no-save", action="store_true",
                        help="do not archive the runs, even if result_management.save_results is true")
    args = parser.parse_args(argv)

    # Values from the command line are not mixed with the config: that could easily contradict
    sampling_config = None
    if any(value is not None for value in (args.count, args.duration, args.frequency)):
        try:
            sampling_config = SamplingConfig.from_values(args.count, args.duration, args.frequency)
        except ConfigError as e:
            # Name the options the user typed, not the config keys
            message = str(e)
            for key, option in ((COUNT_KEY, "--count"), (DURATION_KEY, "--duration"), (FREQUENCY_KEY, "--frequency")):
                message = message.replace(key, option)
            parser.error(message)

    log = TestLogger("run")
    try:
        framework = AmmeterTestFramework(args.config)
    except ConfigError as e:
        log.error(f"Configuration error: {e}")
        return 1

    names = args.ammeter or list(framework.ammeters)
    unknown = [name for name in names if name not in framework.ammeters]
    if unknown:
        parser.error(f"unknown ammeter(s) {unknown}; configured: {list(framework.ammeters)}")
    selected = {name: framework.ammeters[name] for name in names}

    exit_code = 0
    try:
        start_emulators(selected)
    except EmulatorStartError as e:
        # Keep going: the ammeters that did start can still be tested
        log.error(str(e))
        exit_code = 1

    save = framework.save_results and not args.no_save
    plot = save and framework.plot_enabled
    results = {}
    for name in selected:
        log.info(f"Testing {name} ammeter...")
        results[name] = framework.run_test(name, sampling_config)
        if save:
            try:
                record = framework.save(results[name])
                log.info(f"Saved {name} run as {record.run_id}")
            except ArchiveError as e:
                # The result is still printed below; only the archive copy is missing
                log.error(f"Could not save {name} run: {e}")
                exit_code = 1
                continue
            if plot:
                try:
                    path = plot_run(record, framework.archive.directory / f"{record.run_id}.png", framework.plot_types)
                    log.info(f"Saved plot {path.name}")
                except PlotError as e:
                    # Plots are optional: without matplotlib the test itself is complete
                    log.info(f"Plots skipped: {e}")
                    plot = False

    for name, result in results.items():
        print(f"\nResults for {name}:")
        print(framework.report(result))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
