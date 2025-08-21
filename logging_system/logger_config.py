# -*- coding: utf-8 -*-
import logging, logfire, os, sys
from datetime import datetime
from typing import List, Union, Literal, Dict, Optional, Any
from colorama import Fore, Style, init

init(autoreset=True)

# Variable global para almacenar el estado de Logfire
_LOGFIRE_GLOBAL_ENABLED = False
_LOGFIRE_GLOBAL_MIN_LEVEL = 'WARNING'


class ColorFormatter(logging.Formatter):

    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.BLUE,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"


def setup_logging(
    console_output: bool = True, 
    file_output: bool = True, 
    log_directory: str = "logs",
    log_filename: str = "dexes_%Y-%m-%d_%H-%M-%S.log",
    min_level_to_process: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO',
    module_levels: Optional[Dict[str, Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']]] = None,
    enable_logfire: bool = False,
    logfire_config: Optional[Dict[str, Any]] = None,
    logfire_min_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'WARNING'
):
    """
    Configura el sistema de logging con soporte para niveles específicos por módulo y Logfire.
    
    Args:
        console_output: Si se debe mostrar logs en consola
        file_output: Si se debe guardar logs en archivo
        log_directory: Directorio donde se guardarán los logs
        log_filename: Nombre del archivo de logs
        min_level_to_process: Nivel mínimo general para todos los módulos
        module_levels: Diccionario con niveles específicos por módulo
            Ejemplo: {'Module1': 'DEBUG', 'Module2': 'WARNING'}
        enable_logfire: Si se debe habilitar Logfire
        logfire_config: Configuración de Logfire
            Ejemplo: {
                'tags': {'project': 'dexes', 'version': '1.0.0'},
                'service_name': 'dexes-trading',
                'environment': 'development'
            }
        logfire_min_level: Nivel mínimo global para todos los loggers de Logfire
            Opciones: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
            Por defecto: 'WARNING' (para reducir costos)
    """
    handlers: List[Union[logging.FileHandler, logging.StreamHandler]] = []

    if file_output:
        if not os.path.exists(log_directory):
            os.makedirs(log_directory)
        log_filename = datetime.now().strftime(log_filename)
        log_filepath = os.path.join(log_directory, log_filename)
        file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
        handlers.append(file_handler)

    if console_output:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(ColorFormatter('%(name)s - %(levelname)s - %(message)s'))
        handlers.append(stream_handler)

    if not hasattr(logging, min_level_to_process.upper()):
        raise ValueError(f"Invalid log level: {min_level_to_process}. Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL.")

    # Configuración básica del logging
    logging.basicConfig(
        level=getattr(logging, min_level_to_process.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

    # Configurar Logfire si está habilitado
    global _LOGFIRE_GLOBAL_ENABLED, _LOGFIRE_GLOBAL_MIN_LEVEL
    if enable_logfire:
        setup_logfire_global(logfire_config)
        _LOGFIRE_GLOBAL_ENABLED = True
        _LOGFIRE_GLOBAL_MIN_LEVEL = logfire_min_level
    else:
        _LOGFIRE_GLOBAL_ENABLED = False

    # Configuración de niveles específicos por módulo
    if module_levels:
        for module_name, level in module_levels.items():
            if not hasattr(logging, level.upper()):
                raise ValueError(f"Invalid log level for module {module_name}: {level}. Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL.")
            logging.getLogger(module_name).setLevel(getattr(logging, level.upper()))

    # Configuraciones por defecto para librerías externas
    libs = [
        'asyncio',
        'urllib3',
        'telegram.Bot',
        'httpcore.http11',
        'httpcore.connection',
        'websockets.client',
        'httpx',
    ]

    for lib in libs:
        logging.getLogger(lib).setLevel(logging.WARNING)


def setup_logfire_global(logfire_config: Optional[Dict[str, Any]] = None):
    """
    Configura Logfire globalmente para toda la aplicación.
    
    Args:
        logfire_config: Configuración de Logfire
            Ejemplo: {
                'token': 'your_write_token_here',  # Token directo (opcional)
                'tags': {'project': 'dexes', 'version': '1.0.0'},
                'service_name': 'dexes-trading',
                'environment': 'development'
            }

    Nota: El token se puede proporcionar de dos formas:
    1. Variable de entorno: export LOGFIRE_TOKEN="your_token"
    2. Parámetro directo: logfire_config['token'] = "your_token"
    """
    try:
        # Configurar Logfire con los parámetros proporcionados
        config_kwargs = {}

        # Token: prioridad 1) parámetro directo, 2) variable de entorno
        if logfire_config and 'token' in logfire_config:
            config_kwargs['token'] = logfire_config['token']
            print("Using Logfire token from configuration parameter")
        elif os.environ.get('LOGFIRE_TOKEN'):
            config_kwargs['token'] = os.environ.get('LOGFIRE_TOKEN')
            print("Using Logfire token from environment variable LOGFIRE_TOKEN")
        else:
            print("Warning: No Logfire token provided. Using default configuration.")

        # Otros parámetros de configuración
        if logfire_config:
            if 'service_name' in logfire_config:
                config_kwargs['service_name'] = logfire_config['service_name']
            if 'environment' in logfire_config:
                config_kwargs['environment'] = logfire_config['environment']
            if 'service_version' in logfire_config:
                config_kwargs['service_version'] = logfire_config['service_version']

        # Configurar Logfire
        logfire.configure(**config_kwargs)

        # Mostrar configuración (sin mostrar el token por seguridad)
        safe_config = {k: v for k, v in config_kwargs.items() if k != 'token'}
        print(f"Logfire configured successfully with: {safe_config}")

    except Exception as e:
        print(f"Error configuring Logfire: {e}")


def add_logfire_to_logger(logger_name: str, logfire_config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Añade Logfire a un logger específico.
    
    Args:
        logger_name: Nombre del logger
        logfire_config: Configuración de Logfire para este logger
            Ejemplo: {
                'tags': {'component': 'trading'},
                'min_level': 'WARNING'  # Opciones: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
            }
    
    Returns:
        True si se añadió correctamente, False en caso contrario
    """
    try:
        logger = logging.getLogger(logger_name)

        # Crear y agregar el handler de Logfire
        logfire_handler = logfire.LogfireLoggingHandler()

        # Extraer configuración
        tags = logfire_config.get('tags') if logfire_config else None
        # Usar min_level del config específico o el nivel global por defecto
        min_level = logfire_config.get('min_level', _LOGFIRE_GLOBAL_MIN_LEVEL) if logfire_config else _LOGFIRE_GLOBAL_MIN_LEVEL

        # Configurar nivel mínimo para Logfire (por defecto WARNING para reducir costos)
        if hasattr(logging, min_level.upper()):
            logfire_handler.setLevel(getattr(logging, min_level.upper()))
        else:
            print(f"Warning: Invalid log level '{min_level}'. Using WARNING as default.")
            logfire_handler.setLevel(logging.WARNING)

        logger.addHandler(logfire_handler)

        print(f"Logfire handler added to logger: {logger_name} (min_level: {min_level})")
        return True

    except Exception as e:
        print(f"Error adding Logfire handler to logger {logger_name}: {e}")
        return False


def remove_logfire_from_logger(logger_name: str) -> bool:
    """
    Remueve Logfire de un logger específico.
    
    Args:
        logger_name: Nombre del logger
    
    Returns:
        True si se removió correctamente, False en caso contrario
    """
    try:
        logger = logging.getLogger(logger_name)
        handlers_to_remove = [
            h for h in logger.handlers 
            if isinstance(h, logfire.LogfireLoggingHandler)
        ]

        for handler in handlers_to_remove:
            logger.removeHandler(handler)

        print(f"Logfire handlers removed from logger: {logger_name}")
        return True

    except Exception as e:
        print(f"Error removing Logfire handlers from logger {logger_name}: {e}")
        return False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def is_logfire_globally_enabled() -> bool:
    """Retorna True si Logfire está habilitado globalmente en setup_logging()."""
    global _LOGFIRE_GLOBAL_ENABLED
    return _LOGFIRE_GLOBAL_ENABLED


def get_logfire_global_min_level() -> str:
    """Retorna el nivel mínimo global configurado para Logfire."""
    global _LOGFIRE_GLOBAL_MIN_LEVEL
    return _LOGFIRE_GLOBAL_MIN_LEVEL


def get_logfire_instance(tags: Optional[Dict[str, str]] = None):
    """
    Retorna una instancia de Logfire con tags opcionales.
    
    Args:
        tags: Tags adicionales para la instancia
    
    Returns:
        Instancia de Logfire o None si no está disponible
    """
    if tags:
        return logfire.with_tags(*tags.values())
    else:
        return logfire
