"""
    Logging module to set sensibale defaults for test logging
    """
from .config_parser import ConfigParser
import logging
import os


def get_logger(logger_name=None, c_log_level=None, f_log_level=None, logfile=None) -> logging:
    """
    Get a logger with given name either setup or returned if already exists
    Defaults from libs/config.ini will be used if not given here

    :param logger_name: name of the logger, defaults to None
    :type logger_name: str, optional
    :param c_log_level: log level for logging to the console, defaults to None
    :type c_log_level: int, optional
    :param f_log_level: log level for logging to the logfile, defaults to None
    :type f_log_level: int, optional
    :param logfile: logfile location, defaults to None
    :type logfile: str, optional
    :return: connected logger
    :rtype: logging.logger()
    """
    # dont start logger if its a documentation run
    # this is to prevent the creation of log directories when the documentation generation is performed
    try:
        if os.environ["SPHINX"] == 'TRUE':
            return
    except KeyError:
        pass

    cwd = os.environ['TJB_ROOT']

    cf = ConfigParser(f"{cwd}/libs/config.ini")

    if not logger_name:
        logger_name = cf.get_str("LOGGER", "default_logger_name")
    if not c_log_level:
        c_log_level = int(cf.get_str("LOGGER", "default_console_log_level"))
    if not f_log_level:
        f_log_level = int(cf.get_str("LOGGER", "default_logfile_log_level"))
    if not logfile:
        logfile = cf.get_str("LOGGER", "default_logs_file")

    l = Log(logger_name, c_log_level, f_log_level, logfile)
    return l.logger


class Log():
    """
    Logger class that defaults to preset defaults set in libs/config.ini
    """

    def __init__(self, logger_name, console_log_level, file_log_level, logfile):
        # create logger
        self.logger = logging.getLogger(logger_name)
        # check if the logger already has a handler
        if len(self.logger.handlers) == 0:
            self.logger.setLevel(logging.DEBUG)

            os.makedirs(os.path.dirname(logfile), exist_ok=True)

            fh = logging.FileHandler(logfile)
            fh.setLevel(file_log_level)

            # create console handler and set level to debug
            ch = logging.StreamHandler()
            ch.setLevel(console_log_level)

            # create formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

            # add formatter to ch
            ch.setFormatter(formatter)
            fh.setFormatter(formatter)

            # add ch to logger
            self.logger.addHandler(ch)
            self.logger.addHandler(fh)
