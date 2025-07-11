# -*- coding: utf-8 -*-
"""
Sistema de logging estructurado para Copy Trading Mini
"""
import logging
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Optional


class StructuredFormatter(logging.Formatter):
    """Formateador para logs estructurados en JSON"""

    def format(self, record: logging.LogRecord) -> str:
        """Formatea el log record como JSON"""
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # Añadir datos extra si existen
        if hasattr(record, 'extra_data'):
            log_data['data'] = record.extra_data

        # Añadir información de excepción si existe
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        return json.dumps(log_data)


class CopyTradingLogger:
    """Sistema de logging para Copy Trading Mini"""

    def __init__(self,
                    name: str = "CopyTradingMini",
                    level: str = "INFO",
                    log_to_file: bool = True,
                    log_file_path: str = "copy_trading_mini/logs",
                    max_file_size_mb: int = 10,
                    backup_count: int = 5,
                    log_to_console: bool = True):
        """
        Inicializa el logger
        
        Args:
            name: Nombre del logger
            level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_to_file: Si guardar logs en archivo
            log_file_path: Directorio para logs
            max_file_size_mb: Tamaño máximo del archivo de log
            backup_count: Número de archivos de backup
            log_to_console: Si mostrar logs en consola
        """
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.handlers = []  # Limpiar handlers existentes

        # Configurar handler de consola
        if log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, level.upper()))

            # Formato legible para consola
            console_format = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_format)
            self.logger.addHandler(console_handler)

        # Configurar handler de archivo
        if log_to_file:
            # Crear directorio si no existe
            log_path = Path(log_file_path)
            log_path.mkdir(parents=True, exist_ok=True)

            # Archivo de log principal
            log_file = log_path / f"{name.lower()}.log"

            # Handler con rotación
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_file_size_mb * 1024 * 1024,
                backupCount=backup_count
            )
            file_handler.setLevel(getattr(logging, level.upper()))

            # Formato JSON para archivo
            json_formatter = StructuredFormatter()
            file_handler.setFormatter(json_formatter)
            self.logger.addHandler(file_handler)

        # Métricas de logging
        self.metrics = {
            'total_logs': 0,
            'errors': 0,
            'warnings': 0,
            'last_error': None
        }

    def _log_with_data(self, level: str, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Helper para loggear con datos estructurados"""
        self.metrics['total_logs'] += 1

        if level == 'ERROR':
            self.metrics['errors'] += 1
            self.metrics['last_error'] = datetime.utcnow().isoformat()
        elif level == 'WARNING':
            self.metrics['warnings'] += 1

        # Crear un LogRecord con datos extra
        extra = {'extra_data': data} if data else {}

        # Obtener el método de logging correcto
        log_method = getattr(self.logger, level.lower())
        log_method(message, extra=extra, **kwargs)

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None):
        """Log nivel DEBUG"""
        self._log_with_data('DEBUG', message, data)

    def info(self, message: str, data: Optional[Dict[str, Any]] = None):
        """Log nivel INFO"""
        self._log_with_data('INFO', message, data)

    def warning(self, message: str, data: Optional[Dict[str, Any]] = None):
        """Log nivel WARNING"""
        self._log_with_data('WARNING', message, data)

    def error(self, message: str, data: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        """Log nivel ERROR"""
        self._log_with_data('ERROR', message, data, exc_info=exc_info)

    def critical(self, message: str, data: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        """Log nivel CRITICAL"""
        self._log_with_data('CRITICAL', message, data, exc_info=exc_info)

    def log_trade(self, action: str, trader: str, token: str, amount: float, 
                    status: str, details: Optional[Dict[str, Any]] = None):
        """Log específico para trades"""
        trade_data = {
            'trade': {
                'action': action,
                'trader': trader,
                'token': token,
                'amount': amount,
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }
        }

        if details:
            trade_data['trade'].update(details)

        level = 'INFO' if status == 'success' else 'ERROR'
        message = f"Trade {action} - {trader[:8]}... - {amount:.6f} SOL - {status}"
        self._log_with_data(level, message, trade_data)

    def log_position(self, position_id: str, action: str, details: Dict[str, Any]):
        """Log específico para posiciones"""
        position_data = {
            'position': {
                'id': position_id,
                'action': action,
                'timestamp': datetime.utcnow().isoformat(),
                **details
            }
        }

        message = f"Position {action} - {position_id}"
        self.info(message, position_data)

    def log_validation(self, check: str, passed: bool, details: Optional[Dict[str, Any]] = None):
        """Log específico para validaciones"""
        validation_data = {
            'validation': {
                'check': check,
                'passed': passed,
                'timestamp': datetime.utcnow().isoformat()
            }
        }

        if details:
            validation_data['validation'].update(details)

        level = 'DEBUG' if passed else 'WARNING'
        message = f"Validation {check} - {'PASSED' if passed else 'FAILED'}"
        self._log_with_data(level, message, validation_data)

    def log_performance(self, metric: str, value: float, unit: str = "", 
                        context: Optional[Dict[str, Any]] = None):
        """Log de métricas de performance"""
        perf_data = {
            'performance': {
                'metric': metric,
                'value': value,
                'unit': unit,
                'timestamp': datetime.utcnow().isoformat()
            }
        }

        if context:
            perf_data['performance']['context'] = context

        message = f"Performance - {metric}: {value}{unit}"
        self.debug(message, perf_data)

    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del logger"""
        return {
            **self.metrics,
            'current_time': datetime.utcnow().isoformat()
        }

    def reset_metrics(self):
        """Resetea las métricas"""
        self.metrics = {
            'total_logs': 0,
            'errors': 0,
            'warnings': 0,
            'last_error': None
        }
