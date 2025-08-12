# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from .logger_config import get_logger


class AppLogger:

    def __init__(self, name: str):
        self._logger = get_logger(name)
        self._stats = {
            'logger_name': name,
            'start_time': datetime.now().isoformat(),
            'total_logs': 0,
            'level_counts': {
                'DEBUG': 0,
                'INFO': 0,
                'WARNING': 0,
                'ERROR': 0,
                'CRITICAL': 0,
            },
            'last_log_time': None,
            'last_error': None,
            'last_error_time': None,
        }

    def _record(self, level: str, message: str) -> None:
        self._stats['total_logs'] += 1
        if level in self._stats['level_counts']:
            self._stats['level_counts'][level] += 1
        self._stats['last_log_time'] = datetime.now().isoformat()
        if level in ('ERROR', 'CRITICAL'):
            self._stats['last_error'] = message
            self._stats['last_error_time'] = self._stats['last_log_time']

    def debug(self, message: str):
        self._record('DEBUG', message)
        self._logger.debug(message)

    def info(self, message: str):
        self._record('INFO', message)
        self._logger.info(message)

    def warning(self, message: str):
        self._record('WARNING', message)
        self._logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        self._record('ERROR', message)
        self._logger.error(message, exc_info=exc_info)

    def critical(self, message: str, exc_info: bool = False):
        self._record('CRITICAL', message)
        self._logger.critical(message, exc_info=exc_info)

    def stats(self):
        """Devuelve estadísticas y configuración relevante del logger."""
        handlers_info = []
        for handler in self._logger.handlers:
            handler_info = {
                'type': type(handler).__name__,
                'level': logging.getLevelName(handler.level),
            }
            if isinstance(handler, logging.FileHandler):
                handler_info['filename'] = handler.baseFilename
            handlers_info.append(handler_info)

        return {
            'logger_name': self._stats['logger_name'],
            'effective_level': logging.getLevelName(self._logger.getEffectiveLevel()),
            'total_handlers': len(self._logger.handlers),
            'handlers': handlers_info,
            'total_logs': self._stats['total_logs'],
            'level_counts': dict(self._stats['level_counts']),
            'start_time': self._stats['start_time'],
            'last_log_time': self._stats['last_log_time'],
            'last_error': self._stats['last_error'],
            'last_error_time': self._stats['last_error_time'],
        }

    def reset_stats(self):
        """Resetea las estadísticas del logger."""
        self._stats = {
            'logger_name': self._stats['logger_name'],
            'start_time': datetime.now().isoformat(),
            'total_logs': 0,
            'level_counts': {
                'DEBUG': 0,
                'INFO': 0,
                'WARNING': 0,
                'ERROR': 0,
                'CRITICAL': 0,
            },
            'last_log_time': None,
            'last_error': None,
            'last_error_time': None,
        }
