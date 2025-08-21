# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from .logger_config import (
    get_logger, 
    add_logfire_to_logger, 
    remove_logfire_from_logger, 
    get_logfire_instance, 
    is_logfire_globally_enabled,
    get_logfire_global_min_level
)


class AppLogger:

    def __init__(self, name: str, enable_logfire: Optional[bool] = None, logfire_config: Optional[Dict[str, Any]] = None):
        self._logger = get_logger(name)

        # Detectar automáticamente si Logfire está habilitado globalmente
        if enable_logfire is None:
            # Si no se especifica, usar Logfire si está habilitado globalmente
            self._enable_logfire = is_logfire_globally_enabled()
        else:
            self._enable_logfire = enable_logfire

        # Configurar Logfire si está habilitado
        if self._enable_logfire:
            # Añadir handler de Logfire al logger
            add_logfire_to_logger(name, logfire_config)

            # Obtener instancia de Logfire con tags
            tags = logfire_config.get('tags') if logfire_config else None
            self._logfire_instance = get_logfire_instance(tags)
        else:
            self._logfire_instance = None

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
            'logfire_enabled': self._enable_logfire,
            'logfire_connected': self._logfire_instance is not None,
        }

    def _has_global_logfire_config(self) -> bool:
        """
        Verifica si Logfire está configurado globalmente.
        
        Returns:
            True si Logfire está configurado globalmente, False en caso contrario
        """
        try:
            # Verificar si hay algún logger con handler de Logfire
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if hasattr(handler, '__class__') and 'LogfireLoggingHandler' in str(handler.__class__):
                    return True

            # Verificar si hay algún logger específico con handler de Logfire
            for logger_name in logging.root.manager.loggerDict:
                logger = logging.getLogger(logger_name)
                for handler in logger.handlers:
                    if hasattr(handler, '__class__') and 'LogfireLoggingHandler' in str(handler.__class__):
                        return True

            # Verificar si Logfire está configurado globalmente (aunque no haya handlers)
            # Esto es útil cuando setup_logging() configuró Logfire pero no agregó handlers específicos
            try:
                # Si logfire está configurado, intentar obtener una instancia
                logfire_instance = get_logfire_instance()
                return logfire_instance is not None
            except Exception:
                return False

        except Exception:
            return False

    def _record(self, level: str, message: str) -> None:
        self._stats['total_logs'] += 1
        if level in self._stats['level_counts']:
            self._stats['level_counts'][level] += 1
        self._stats['last_log_time'] = datetime.now().isoformat()
        if level in ('ERROR', 'CRITICAL'):
            self._stats['last_error'] = message
            self._stats['last_error_time'] = self._stats['last_log_time']

    def debug(self, message: str, **extra):
        self._record('DEBUG', message)
        self._logger.debug(message, extra=extra)

    def info(self, message: str, **extra):
        self._record('INFO', message)
        self._logger.info(message, extra=extra)

    def warning(self, message: str, **extra):
        self._record('WARNING', message)
        self._logger.warning(message, extra=extra)

    def error(self, message: str, exc_info: bool = False, **extra):
        self._record('ERROR', message)
        self._logger.error(message, exc_info=exc_info, extra=extra)

    def critical(self, message: str, exc_info: bool = False, **extra):
        self._record('CRITICAL', message)
        self._logger.critical(message, exc_info=exc_info, extra=extra)

    def span(self, message: str, **attributes):
        """
        Crear un span usando Logfire (solo disponible si Logfire está habilitado).
        Si Logfire no está disponible, crea un log normal.
        """
        if self._logfire_instance:
            return self._logfire_instance.span(message, **attributes)
        else:
            # Fallback: crear un log normal
            self.info(f"SPAN: {message}", **attributes)
            return DummySpan()

    def enable_logfire(self, logfire_config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Habilita Logfire para este logger.
        
        Args:
            logfire_config: Configuración de Logfire
            
        Returns:
            True si se habilitó correctamente, False en caso contrario
        """
        if self._logfire_instance:
            return True  # Ya está habilitado

        # Añadir handler de Logfire
        tags = logfire_config.get('tags') if logfire_config else None
        # Si no hay logfire_config, crear uno con el nivel global por defecto
        if not logfire_config:
            logfire_config = {'min_level': get_logfire_global_min_level()}
        elif 'min_level' not in logfire_config:
            # Si hay config pero no min_level, usar el global
            logfire_config['min_level'] = get_logfire_global_min_level()

        if add_logfire_to_logger(self._logger.name, logfire_config):
            self._logfire_instance = get_logfire_instance(tags)
            self._enable_logfire = True
            self._stats['logfire_enabled'] = True
            self._stats['logfire_connected'] = True
            return True
        return False

    def disable_logfire(self) -> bool:
        """
        Deshabilita Logfire para este logger.
        
        Returns:
            True si se deshabilitó correctamente, False en caso contrario
        """
        if not self._logfire_instance:
            return True  # Ya está deshabilitado

        if remove_logfire_from_logger(self._logger.name):
            self._logfire_instance = None
            self._enable_logfire = False
            self._stats['logfire_enabled'] = False
            self._stats['logfire_connected'] = False
            return True
        return False

    def is_logfire_enabled(self) -> bool:
        """Retorna True si Logfire está habilitado."""
        return bool(self._enable_logfire and self._logfire_instance is not None)

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
            elif hasattr(handler, '__class__') and 'LogfireLoggingHandler' in str(handler.__class__):
                handler_info['logfire'] = 'True'
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
            'logfire_enabled': self._stats['logfire_enabled'],
            'logfire_connected': self._stats['logfire_connected'],
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
            'logfire_enabled': self._stats['logfire_enabled'],
            'logfire_connected': self._stats['logfire_connected'],
        }


class DummySpan:
    """Span dummy para cuando Logfire no está disponible."""
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
