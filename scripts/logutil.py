import airbrake
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_logger(env, airbrake_enabled, log_level, handle_unhandled_exceptions=False):
    log = airbrake.getLogger() if airbrake_enabled else logging.getLogger()
    log.setLevel(log_level)
    
    fmt = '%(asctime)s - %(name)s({env}) - %(levelname)s - %(message)s'.format(
        env=env)
    formatter = logging.Formatter(fmt)

    path = str(Path(__file__, "..", "..", "logs", "covid_algotracker_%s.log" % env))
    file_handler = RotatingFileHandler(path, 'a', 32 * 1000 * 1024, 1000)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    print("Logging to %s" % path)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    log.addHandler(stdout_handler)

    if handle_unhandled_exceptions:
        def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            log.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.excepthook = handle_unhandled_exception

    return log

