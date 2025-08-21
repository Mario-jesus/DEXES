# Sistema de Logging Integrado con Logfire

Este módulo proporciona un sistema de logging completo que combina logging tradicional de Python con Logfire para observabilidad en la nube, usando la **integración oficial** de Logfire con **configuración centralizada**.

## Características

- ✅ **Logging tradicional**: Consola con colores y archivos locales
- ✅ **Logfire integrado**: Envío automático usando `LogfireLoggingHandler` oficial
- ✅ **Configuración centralizada**: Toda la configuración en `logger_config.py`
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
    console_output=True,
    file_output=True,
    enable_logfire=True,
    logfire_config={
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'min_level': 'WARNING',  # Solo WARNING, ERROR, CRITICAL (por defecto)
        'tags': {
            'project': 'dexes',
            'version': '1.0.0'
        }
        # No incluir 'token' aquí - se usa LOGFIRE_TOKEN del entorno
    }
)

# Opción B: Token directo (solo para desarrollo/pruebas)
setup_logging(
    console_output=True,
    file_output=True,
    enable_logfire=True,
    logfire_config={
        'token': '__YOUR_LOGFIRE_WRITE_TOKEN__',  # Reemplazar con tu token
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'tags': {
            'project': 'dexes',
            'version': '1.0.0'
        }
    }
)

# Crear logger (Logfire ya está configurado)
logger = AppLogger(
    name='trading_bot',
    enable_logfire=True,  # Añadir Logfire a este logger
    logfire_config={'tags': {'component': 'trading_bot'}}  # Tags adicionales
)
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
add_logfire_to_logger('trading_bot', {'component': 'trading'})
add_logfire_to_logger('price_tracker', {'component': 'tracking'})
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
    'min_level': 'WARNING',  # Solo WARNING, ERROR, CRITICAL (por defecto)
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
    'min_level': 'INFO',  # INFO, WARNING, ERROR, CRITICAL
    'tags': {
        'project': 'dexes',
        'deployment': 'aws-ec2',
        'team': 'trading'
    }
}

# Opción 3: Para debugging completo
logfire_config = {
    'min_level': 'DEBUG',  # Todos los niveles (puede ser costoso)
    'tags': {'project': 'dexes'}
}
```

### Niveles Mínimos para Logfire

Por defecto, Logfire solo envía logs de nivel **WARNING** en adelante para reducir costos:

- **`'WARNING'`** (por defecto): Solo WARNING, ERROR, CRITICAL
- **`'ERROR'`**: Solo ERROR, CRITICAL  
- **`'INFO'`**: INFO, WARNING, ERROR, CRITICAL
- **`'DEBUG'`**: Todos los niveles (puede ser costoso)

### Prioridad de Configuración del Token

1. **Parámetro directo**: `logfire_config['token']` (más alta prioridad)
2. **Variable de entorno**: `LOGFIRE_TOKEN` (recomendado para producción)
3. **Sin token**: Usa configuración por defecto (puede no funcionar)

### Múltiples Loggers con Tags Diferentes

```python
# Configurar Logfire globalmente
setup_logging(
    enable_logfire=True,
    logfire_config={
        'service_name': 'dexes-trading',
        'tags': {'project': 'dexes', 'version': '1.0.0'}
    }
)

# Logger principal
main_logger = AppLogger('main', enable_logfire=True, 
                       logfire_config={'tags': {'component': 'main'}})

# Logger específico para trading
trading_logger = AppLogger('trading', enable_logfire=True,
                          logfire_config={'tags': {'component': 'trading'}})

# Logger para debugging (sin Logfire)
debug_logger = AppLogger('debug', enable_logfire=False)
```

## Funciones Disponibles

### Configuración Centralizada
- `setup_logging()` - Configura todo el sistema de logging
- `setup_logfire_global()` - Configura Logfire globalmente
- `add_logfire_to_logger()` - Añade Logfire a un logger específico (min_level por defecto: WARNING)
- `remove_logfire_from_logger()` - Remueve Logfire de un logger
- `get_logfire_instance()` - Obtiene instancia de Logfire con tags
- `is_logfire_available()` - Verifica si Logfire está disponible

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
```

## Ejemplos de Uso

### Ejemplo Completo
Ver `docs/examples/example_usage.py` para un ejemplo completo de configuración y uso del sistema, incluyendo:
- Configuración básica y avanzada
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
    enable_logfire=True,
    logfire_config={
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'min_level': 'WARNING',  # Solo WARNING, ERROR, CRITICAL (por defecto)
        'tags': {'project': 'dexes', 'version': '1.0.0'}
    }
)

# Crear logger
logger = AppLogger('trading_bot', enable_logfire=True)

# Usar el logger
logger.info("Sistema iniciado")
logger.error("Error de ejemplo", exc_info=True)

# Ver estadísticas
stats = logger.stats()
print(f"Total logs: {stats['total_logs']}")
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