# Sistema de Logging Integrado con Logfire

Este módulo proporciona un sistema de logging completo que combina logging tradicional de Python con Logfire para observabilidad en la nube, usando la **integración oficial** de Logfire con **configuración centralizada** y **detección automática**.

## Características

- ✅ **Logging tradicional**: Consola con colores y archivos locales
- ✅ **Logfire integrado**: Envío automático usando `LogfireLoggingHandler` oficial
- ✅ **Configuración centralizada**: Toda la configuración en `logger_config.py`
- ✅ **Detección automática**: `AppLogger` detecta automáticamente si Logfire está habilitado en `setup_logging()`
- ✅ **Estadísticas en tiempo real**: Seguimiento de logs y métricas
- ✅ **Configuración flexible**: Niveles por módulo y configuración granular
- ✅ **Campos extra**: Soporte para metadatos estructurados usando `extra=`
- ✅ **Control dinámico**: Habilitar/deshabilitar Logfire en tiempo de ejecución
- ✅ **Spans**: Soporte para tracing con Logfire

## Instalación

```bash
# Logfire ya está incluido en Pipfile
pipenv install
```

## Configuración

### 1. Variables de Entorno (Recomendado para Producción)

```bash
# Para Logfire (REQUERIDO)
export LOGFIRE_TOKEN="your_write_token_here"

# Opcionales
export LOGFIRE_SERVICE_NAME="dexes-trading"
export LOGFIRE_ENVIRONMENT="development"
```

### 2. Configuración Centralizada (Recomendado)

```python
from logging_system import setup_logging, AppLogger

# Opción A: Token desde variable de entorno (SEGURIDAD)
setup_logging(
    # Configuración de salida
    console_output=True,           # Mostrar logs en consola
    file_output=True,              # Guardar logs en archivo
    
    # Configuración de archivos
    log_directory="logs",          # Directorio para archivos de log
    log_filename="dexes_%Y-%m-%d_%H-%M-%S.log",  # Formato del nombre de archivo
    
    # Configuración de niveles
    min_level_to_process='INFO',   # Nivel mínimo general (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    module_levels={                # Niveles específicos por módulo
        'trading_bot': 'INFO',
        'price_tracker': 'DEBUG',
        'wallet_manager': 'WARNING'
    },
    
    # Configuración de Logfire
    enable_logfire=True,           # ✅ Habilitar Logfire globalmente
    logfire_config={
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'tags': {
            'project': 'dexes',
            'version': '1.0.0'
        }
        # No incluir 'token' aquí - se usa LOGFIRE_TOKEN del entorno
    },
    logfire_min_level='WARNING'    # ✅ Nivel global para todos los loggers de Logfire
)

# ✅ Detección automática - AppLogger detecta que Logfire está habilitado
logger = AppLogger(name='trading_bot')  # Logfire habilitado automáticamente

# ✅ Sobrescribir explícitamente si es necesario
logger_without_logfire = AppLogger(name='debug_logger', enable_logfire=False)
logger_with_logfire = AppLogger(name='trading_logger', enable_logfire=True)
```

### 3. Configuración Manual (Avanzado)

```python
from logging_system import setup_logging, setup_logfire_global, add_logfire_to_logger

# Configurar logging base
setup_logging(console_output=True, file_output=True)

# Configurar Logfire globalmente
setup_logfire_global({
    'service_name': 'dexes-trading',
    'environment': 'development'
})

# Añadir Logfire a loggers específicos
add_logfire_to_logger('trading_bot', {
    'tags': {'component': 'trading'},
    'min_level': 'WARNING'
})
add_logfire_to_logger('price_tracker', {
    'tags': {'component': 'tracking'},
    'min_level': 'INFO'
})
```

## Uso

### Logs Básicos

```python
logger.info("Sistema iniciado")
logger.debug("Configuración cargada")
logger.warning("Precio fuera de rango")
logger.error("Error en transacción", exc_info=True)
```

### Logs con Campos Extra (Recomendado para Logfire)

```python
logger.info(
    "Nueva transacción",
    extra={
        'transaction_id': 'tx_12345',
        'amount': 100.50,
        'token': 'SOL',
        'wallet_address': 'ABC123...'
    }
)

logger.error(
    "Error procesando transacción",
    exc_info=True,
    extra={
        'transaction_id': 'tx_12345',
        'error_type': 'ValueError'
    }
)
```

### Spans para Tracing

```python
# Spans (solo disponibles con Logfire habilitado)
with logger.span("Procesando transacción", transaction_id="tx_12345"):
    logger.info("Transacción procesada exitosamente")
```

### Control Dinámico de Logfire

```python
# Verificar estado
if logger.is_logfire_enabled():
    print("Logfire está activo")

# Deshabilitar Logfire
logger.disable_logfire()

# Habilitar Logfire nuevamente
logger.enable_logfire({'tags': {'component': 'trading'}})
```

### Estadísticas

```python
stats = logger.stats()
print(f"Total logs: {stats['total_logs']}")
print(f"Logfire conectado: {stats['logfire_connected']}")
print(f"Conteo por nivel: {stats['level_counts']}")
print(f"Handlers: {[h['type'] for h in stats['handlers']]}")
```

## Estructura de Archivos

```
logging_system/
├── __init__.py              # Interfaz pública del módulo
├── logger_config.py         # Configuración centralizada (Logfire + logging)
├── custom_logger.py         # AppLogger con estadísticas y control de Logfire
└── docs/
    ├── README.md           # Esta documentación
    └── examples/
        └── example_usage.py # Ejemplo completo de uso
```

### Descripción de Archivos

- **`__init__.py`**: Exporta todas las funciones públicas del módulo
- **`logger_config.py`**: Configuración centralizada del sistema de logging y Logfire
- **`custom_logger.py`**: Clase AppLogger que combina logging tradicional con Logfire
- **`docs/README.md`**: Documentación completa del sistema
- **`docs/examples/example_usage.py`**: Ejemplo completo de configuración y uso del sistema

## Parámetros de Configuración

### Parámetros de `setup_logging()`

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `console_output` | `bool` | `True` | Mostrar logs en consola con colores |
| `file_output` | `bool` | `True` | Guardar logs en archivo |
| `log_directory` | `str` | `"logs"` | Directorio donde se guardarán los archivos de log |
| `log_filename` | `str` | `"dexes_%Y-%m-%d_%H-%M-%S.log"` | Formato del nombre de archivo (usa strftime) |
| `min_level_to_process` | `str` | `'INFO'` | Nivel mínimo general para todos los módulos |
| `module_levels` | `Dict[str, str]` | `None` | Niveles específicos por módulo |
| `enable_logfire` | `bool` | `False` | Habilitar Logfire globalmente |
| `logfire_config` | `Dict[str, Any]` | `None` | Configuración específica de Logfire |
| `logfire_min_level` | `str` | `'WARNING'` | Nivel mínimo global para todos los loggers de Logfire |

### Ejemplos de Configuración de Archivos

```python
# Configuración básica de archivos
setup_logging(
    log_directory="my_logs",                    # Directorio personalizado
    log_filename="app_%Y-%m-%d.log"            # Nombre de archivo personalizado
)

# Configuración sin archivos (solo consola)
setup_logging(
    file_output=False,                          # No guardar en archivo
    console_output=True                         # Solo mostrar en consola
)

# Configuración solo archivos (sin consola)
setup_logging(
    console_output=False,                       # No mostrar en consola
    file_output=True,                           # Solo guardar en archivo
    log_directory="production_logs"             # Directorio de producción
)
```

### Ejemplos de Niveles de Logging

```python
# Nivel general para toda la aplicación
setup_logging(
    min_level_to_process='DEBUG'                # Todos los logs
)

# Niveles específicos por módulo
setup_logging(
    min_level_to_process='INFO',                # Nivel general
    module_levels={
        'trading_bot': 'DEBUG',                 # Más detallado para trading
        'price_tracker': 'INFO',                # Normal para price tracker
        'wallet_manager': 'WARNING',            # Solo warnings y errores
        'dex_analyzer': 'ERROR'                 # Solo errores
    }
)
```

## Configuración Avanzada

### Niveles por Módulo

```python
setup_logging(
    module_levels={
        'trading_bot': 'INFO',
        'price_tracker': 'DEBUG',
        'wallet_manager': 'WARNING',
        'dex_analyzer': 'ERROR'
    }
)
```

### Configuración de Logfire Detallada

```python
# Opción 1: Token desde variable de entorno (SEGURIDAD)
logfire_config = {
    'service_name': 'dexes-trading-bot',
    'environment': 'production',
    'service_version': '1.0.0',
    'tags': {
        'project': 'dexes',
        'deployment': 'aws-ec2',
        'team': 'trading'
    }
    # No incluir 'token' - se usa LOGFIRE_TOKEN del entorno
}

# Opción 2: Token directo (solo desarrollo)
logfire_config = {
    'token': 'your_write_token_here',  # Reemplazar con tu token real
    'service_name': 'dexes-trading-bot',
    'environment': 'production',
    'service_version': '1.0.0',
    'tags': {
        'project': 'dexes',
        'deployment': 'aws-ec2',
        'team': 'trading'
    }
}
```

### Niveles Mínimos para Logfire

#### Configuración Global (Recomendado)

El nivel mínimo se puede configurar **globalmente** en `setup_logging()`:

```python
# Configuración global para todos los loggers de Logfire
setup_logging(
    enable_logfire=True,
    logfire_config={'service_name': 'dexes-trading'},
    logfire_min_level='WARNING'  # ✅ Nivel global para todos los loggers
)

# Todos los loggers usarán WARNING por defecto
logger1 = AppLogger('trading')  # Usa WARNING automáticamente
logger2 = AppLogger('price')    # Usa WARNING automáticamente
```

#### Configuración Específica por Logger

También se puede sobrescribir el nivel para loggers específicos:

```python
# Configuración global
setup_logging(
    enable_logfire=True,
    logfire_config={'service_name': 'dexes-trading'},
    logfire_min_level='WARNING'  # Nivel global
)

# Logger específico con nivel diferente
debug_logger = AppLogger('debug', enable_logfire=True, logfire_config={
    'min_level': 'DEBUG'  # ✅ Sobrescribe el nivel global
})

# Logger que usa el nivel global
normal_logger = AppLogger('normal')  # ✅ Usa WARNING automáticamente
```

#### Niveles Disponibles

Por defecto, Logfire solo envía logs de nivel **WARNING** en adelante para reducir costos:

- **`'WARNING'`** (por defecto): Solo WARNING, ERROR, CRITICAL
- **`'ERROR'`**: Solo ERROR, CRITICAL  
- **`'INFO'`**: INFO, WARNING, ERROR, CRITICAL
- **`'DEBUG'`**: Todos los niveles (puede ser costoso)

### Prioridad de Configuración del Token

1. **Parámetro directo**: `logfire_config['token']` (más alta prioridad)
2. **Variable de entorno**: `LOGFIRE_TOKEN` (recomendado para producción)
3. **Sin token**: Usa configuración por defecto (puede no funcionar)

### Múltiples Loggers con Detección Automática

```python
# Configurar Logfire globalmente
setup_logging(
    enable_logfire=True,  # ✅ Habilitar Logfire globalmente
    logfire_config={
        'service_name': 'dexes-trading',
        'tags': {'project': 'dexes', 'version': '1.0.0'}
    }
)

# ✅ Detección automática - todos estos loggers tendrán Logfire habilitado
main_logger = AppLogger('main')
trading_logger = AppLogger('trading')
price_logger = AppLogger('price_tracker')

# ✅ Sobrescribir explícitamente si es necesario
debug_logger = AppLogger('debug', enable_logfire=False)  # Sin Logfire
specific_logger = AppLogger('specific', enable_logfire=True, 
                           logfire_config={'tags': {'component': 'specific'}})
```

## Funciones Disponibles

### Configuración Centralizada
- `setup_logging()` - Configura todo el sistema de logging
- `setup_logfire_global()` - Configura Logfire globalmente
- `add_logfire_to_logger()` - Añade Logfire a un logger específico usando logfire_config
- `remove_logfire_from_logger()` - Remueve Logfire de un logger
- `get_logfire_instance()` - Obtiene instancia de Logfire con tags
- `is_logfire_globally_enabled()` - Verifica si Logfire está habilitado globalmente
- `get_logfire_global_min_level()` - Obtiene el nivel mínimo global configurado para Logfire

### AppLogger
- `AppLogger()` - Logger con estadísticas y control de Logfire
- `logger.span()` - Crear spans para tracing
- `logger.enable_logfire()` - Habilitar Logfire dinámicamente
- `logger.disable_logfire()` - Deshabilitar Logfire dinámicamente
- `logger.stats()` - Obtener estadísticas del logger

## Beneficios de la Configuración Centralizada

### Antes (Complejo)
```python
# Configuración dispersa en múltiples archivos
import logfire
logfire.configure()
logfire_handler = logfire.LogfireLoggingHandler()
logger.addHandler(logfire_handler)
```

### Ahora (Simple)
```python
# Todo en una sola llamada
setup_logging(
    enable_logfire=True,
    logfire_config={'service_name': 'dexes-trading'}
)

# ✅ Detección automática
logger = AppLogger('trading_bot')  # Logfire habilitado automáticamente
```

## Ejemplos de Uso

### Ejemplo Completo
Ver `docs/examples/example_usage.py` para un ejemplo completo de configuración y uso del sistema, incluyendo:
- Configuración básica y avanzada
- Detección automática de Logfire
- Múltiples loggers con tags diferentes
- Control dinámico de Logfire
- Ejemplos de troubleshooting

### Ejemplo Rápido

```python
from logging_system import setup_logging, AppLogger

# Configurar sistema completo
setup_logging(
    console_output=True,
    file_output=True,
    enable_logfire=True,  # ✅ Habilitar Logfire globalmente
    logfire_config={
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'tags': {'project': 'dexes', 'version': '1.0.0'}
    }
)

# ✅ Detección automática - no necesitas especificar enable_logfire
logger = AppLogger('trading_bot')  # Logfire habilitado automáticamente

# Usar el logger
logger.info("Sistema iniciado")
logger.error("Error de ejemplo", exc_info=True)

# Ver estadísticas
stats = logger.stats()
print(f"Total logs: {stats['total_logs']}")
print(f"Logfire habilitado: {stats['logfire_enabled']}")
```

## Troubleshooting

### Logfire no se conecta
1. **Verificar token**: Asegúrate de que `LOGFIRE_TOKEN` esté configurado
   ```bash
   # Verificar variable de entorno
   echo $LOGFIRE_TOKEN
   
   # O configurar si no existe
   export LOGFIRE_TOKEN="your_write_token_here"
   ```
2. **Verificar token en código**: Si usas token directo, asegúrate de reemplazar `__YOUR_LOGFIRE_WRITE_TOKEN__`
3. **Verificar conexión a internet**
4. **Revisar configuración de firewall**

### Logs no aparecen en Logfire
1. Verificar que Logfire esté habilitado: `logger.is_logfire_enabled()`
2. Revisar estadísticas: `logger.stats()`
3. Verificar que `setup_logging(enable_logfire=True)` se haya llamado
4. Verificar que `AppLogger` detecte automáticamente el estado global

### Errores de importación
```bash
pip install logfire
# o
pipenv install logfire
```

### Campos extra no aparecen
- Usar `extra={...}` en lugar de parámetros directos
- Los campos extra van en el parámetro `extra` del método de logging

### Configuración duplicada
- Usar `setup_logging()` una sola vez al inicio de la aplicación
- No llamar `logfire.configure()` manualmente
- `AppLogger` detecta automáticamente el estado de Logfire desde `setup_logging()`

### Detección automática no funciona
- Asegúrate de llamar `setup_logging(enable_logfire=True)` antes de crear `AppLogger`
- Si necesitas sobrescribir el comportamiento, usa `enable_logfire=False` o `enable_logfire=True` explícitamente