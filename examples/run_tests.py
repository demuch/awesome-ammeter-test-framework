import sys
from pathlib import Path

# Make 'src' and 'Ammeters' importable when the script is started as 'python examples/run_tests.py'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import ConfigError
from src.utils.emulators import EmulatorStartError, start_emulators


def main():
    """
    Starts the emulators and runs the configured sampling test on every ammeter in config.yaml,
    then prints one report per ammeter.
    """
    # יצירת מסגרת הבדיקות
    try:
        framework = AmmeterTestFramework()
        start_emulators(framework.ammeters)
    except ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    except EmulatorStartError as e:
        # Keep going: the ammeters that did start can still be tested
        print(e)

    # הרצת בדיקות לכל סוגי האמפרמטרים
    results = {}
    for ammeter_type in framework.ammeters:
        print(f"Testing {ammeter_type} ammeter...")
        results[ammeter_type] = framework.run_test(ammeter_type)

    # השוואת תוצאות
    for ammeter_type, result in results.items():
        print(f"\nResults for {ammeter_type}:")
        print(framework.report(result))


if __name__ == "__main__":
    main()
