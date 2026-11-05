import logging
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class TestLogger:
    def __init__(self, test_name: str):
        self._test_name = test_name
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """
        הגדרת הלוגר עם פורמט מותאם וכתיבה לקובץ
        """
        # יצירת תיקיית הלוגים
        # Relative to the project root, not the current directory
        log_dir = PROJECT_ROOT / "results" / "logs"
        os.makedirs(log_dir, exist_ok=True)

        # הגדרת שם הקובץ עם תאריך ומזהה הבדיקה
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{timestamp}_{self._test_name}.log"

        # הגדרת הלוגר
        logger = logging.getLogger(f"test_{self._test_name}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # Do not print every message a second time via the root logger

        # getLogger() returns the same object for the same name: drop handlers from a previous
        # TestLogger with this name, otherwise every message would be written twice
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        formatter = logging.Formatter(LOG_FORMAT)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Full history in the file
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)  # Keep the console readable
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        return logger

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message) 