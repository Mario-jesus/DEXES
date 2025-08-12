# -*- coding: utf-8 -*-
import logging, os, sys
from datetime import datetime
from typing import List, Union, Literal, Dict, Optional
from colorama import Fore, Style, init

init(autoreset=True)


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
    min_level_to_process: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO',
    module_levels: Optional[Dict[str, Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']]] = None
):
    """
    Configura el sistema de logging con soporte para niveles específicos por módulo.
    
    Args:
        console_output: Si se debe mostrar logs en consola
        file_output: Si se debe guardar logs en archivo
        min_level_to_process: Nivel mínimo general para todos los módulos
        module_levels: Diccionario con niveles específicos por módulo
            Ejemplo: {'Module1': 'DEBUG', 'Module2': 'WARNING'}
    """
    handlers: List[Union[logging.FileHandler, logging.StreamHandler]] = []
    if file_output:
        log_directory = "logs"
        if not os.path.exists(log_directory):
            os.makedirs(log_directory)
        log_filename = datetime.now().strftime("copy_trading_%Y-%m-%d_%H-%M-%S.log")
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

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
