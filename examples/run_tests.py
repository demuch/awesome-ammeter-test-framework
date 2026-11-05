import sys
from pathlib import Path

# Make 'src' and 'Ammeters' importable when the script is started as 'python examples/run_tests.py'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.testing.archive import ArchiveError
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import ConfigError
from src.utils.emulators import EmulatorStartError, start_emulators
from src.utils.logger import TestLogger


def main():
    """
    Starts the emulators, runs the configured sampling test on every ammeter in config.yaml,
    archives each run if ``result_management.save_results`` is true, then prints one report per ammeter.
    Events are logged to the console and to a file in ``results/logs``.
    """
    log = TestLogger("run_tests")

    # יצירת מסגרת הבדיקות
    try:
        framework = AmmeterTestFramework()
        start_emulators(framework.ammeters)
    except ConfigError as e:
        log.error(f"Configuration error: {e}")
        sys.exit(1)
    except EmulatorStartError as e:
        # Keep going: the ammeters that did start can still be tested
        log.warning(str(e))

    # הרצת בדיקות לכל סוגי האמפרמטרים
    results = {}
    for ammeter_type in framework.ammeters:
        log.info(f"Testing {ammeter_type} ammeter...")
        results[ammeter_type] = framework.run_test(ammeter_type)
        if framework.save_results:
            try:
                record = framework.save(results[ammeter_type])
                log.info(f"Saved {ammeter_type} run as {record.run_id}")
            except ArchiveError as e:
                # The result is still printed below; only the archive copy is missing
                log.error(f"Could not save {ammeter_type} run: {e}")

    # השוואת תוצאות
    for ammeter_type, result in results.items():
        print(f"\nResults for {ammeter_type}:")
        print(framework.report(result))


if __name__ == "__main__":
    main()
