# -*- coding: utf-8 -*-
"""
Ejemplo de uso del sistema de logging integrado con Logfire.
Usando la configuración centralizada desde logger_config con detección automática.
"""
import os
from logging_system import setup_logging, AppLogger

def main():
    print("=== EJEMPLO CON DETECCIÓN AUTOMÁTICA DE LOGFIRE ===")

    # Opción 1: Token desde variable de entorno (RECOMENDADO para producción)
    # export LOGFIRE_TOKEN="your_write_token_here"

    # Opción 2: Token desde configuración directa (para desarrollo/pruebas)
    logfire_config = {
        'token': '__YOUR_LOGFIRE_WRITE_TOKEN__',  # Reemplazar con tu token real
        'service_name': 'dexes-trading-bot',
        'environment': 'development',
        'tags': {
            'project': 'dexes',
            'version': '1.0.0'
        }
    }

    # Configurar el sistema de logging base CON Logfire habilitado
    setup_logging(
        # Configuración de salida
        console_output=True,           # Mostrar logs en consola
        file_output=True,              # Guardar logs en archivo

        # Configuración de archivos
        log_directory="logs",          # Directorio para archivos de log
        log_filename="dexes_%Y-%m-%d_%H-%M-%S.log",  # Formato del nombre de archivo

        # Configuración de niveles
        min_level_to_process='DEBUG',  # Nivel mínimo general
        module_levels={                # Niveles específicos por módulo
            'trading_bot': 'INFO',
            'price_tracker': 'DEBUG'
        },

        # Configuración de Logfire
        enable_logfire=True,           # ✅ Habilitar Logfire globalmente
        logfire_config=logfire_config  # Configuración de Logfire
    )

    # ✅ DETECCIÓN AUTOMÁTICA - AppLogger detecta que Logfire está habilitado
    logger = AppLogger(name='trading_bot')  # Logfire habilitado automáticamente

    # Logs básicos (van a consola, archivo y Logfire)
    logger.info("Sistema de trading iniciado")
    logger.debug("Configuración cargada")

    # Logs con campos extra (especialmente útiles para Logfire)
    logger.info(
        "Nueva transacción detectada",
        extra={
            'transaction_id': 'tx_12345',
            'amount': 100.50,
            'token': 'SOL',
            'wallet_address': 'ABC123...'
        }
    )

    # Logs de error con información adicional
    try:
        # Simular un error
        raise ValueError("Error en la transacción")
    except Exception as e:
        logger.error(
            "Error procesando transacción",
            exc_info=True,
            extra={
                'transaction_id': 'tx_12345',
                'error_type': type(e).__name__
            }
        )

    # Logs de warning con contexto
    logger.warning(
        "Precio fuera de rango esperado",
        extra={
            'current_price': 95.50,
            'expected_range': (100, 110),
            'token': 'SOL'
        }
    )

    # Spans para tracing (solo disponible con Logfire)
    with logger.span("Procesando transacción", transaction_id="tx_12345"):
        logger.info("Transacción procesada exitosamente")

    # Verificar estadísticas
    stats = logger.stats()
    print("\n=== Estadísticas del Logger ===")
    print(f"Total de logs: {stats['total_logs']}")
    print(f"Logfire habilitado: {stats['logfire_enabled']}")
    print(f"Logfire conectado: {stats['logfire_connected']}")
    print(f"Conteo por nivel: {stats['level_counts']}")
    print(f"Handlers configurados: {[h['type'] for h in stats['handlers']]}")

    # Ejemplo de habilitar/deshabilitar Logfire dinámicamente
    print("\n=== Prueba de control dinámico ===")

    # Deshabilitar Logfire
    if logger.disable_logfire():
        print("Logfire deshabilitado")
        logger.info("Este log solo va a consola y archivo")

    # Habilitar Logfire nuevamente
    if logger.enable_logfire({'tags': {'component': 'trading_bot'}}):
        print("Logfire habilitado nuevamente")
        logger.info("Este log va a consola, archivo y Logfire")

    # Verificar estado final
    print(f"Logfire habilitado: {logger.is_logfire_enabled()}")


def example_detection_automatic():
    """Ejemplo demostrando la detección automática de Logfire."""
    print("\n=== EJEMPLO DE DETECCIÓN AUTOMÁTICA ===")

    # Configurar Logfire globalmente
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

    # ✅ DETECCIÓN AUTOMÁTICA - todos estos loggers tendrán Logfire habilitado
    main_logger = AppLogger('main')
    trading_logger = AppLogger('trading')
    price_logger = AppLogger('price_tracker')

    # ✅ SOBRESCRIBIR EXPLÍCITAMENTE si es necesario
    debug_logger = AppLogger('debug', enable_logfire=False)  # Sin Logfire
    specific_logger = AppLogger('specific', enable_logfire=True, 
                                logfire_config={'tags': {'component': 'specific'}})

    # Verificar estados
    print(f"Main logger - Logfire: {main_logger.is_logfire_enabled()}")
    print(f"Trading logger - Logfire: {trading_logger.is_logfire_enabled()}")
    print(f"Price logger - Logfire: {price_logger.is_logfire_enabled()}")
    print(f"Debug logger - Logfire: {debug_logger.is_logfire_enabled()}")
    print(f"Specific logger - Logfire: {specific_logger.is_logfire_enabled()}")

    # Enviar logs de prueba
    main_logger.info("Logger principal con detección automática")
    trading_logger.warning("Logger de trading con detección automática")
    debug_logger.info("Logger de debug sin Logfire")
    specific_logger.error("Logger específico con configuración personalizada")


def example_with_environment_token():
    """Ejemplo usando token desde variable de entorno."""
    print("\n=== EJEMPLO CON TOKEN DESDE VARIABLE DE ENTORNO ===")

    # Configurar token desde variable de entorno
    # export LOGFIRE_TOKEN="your_write_token_here"

    # Configuración sin token en el código (usa variable de entorno)
    logfire_config = {
        'service_name': 'dexes-trading-bot',
        'environment': 'production',
        'tags': {
            'project': 'dexes',
            'version': '1.0.0',
            'deployment': 'aws-ec2'
        }
    }

    setup_logging(
        console_output=True,
        file_output=True,
        enable_logfire=True,  # ✅ Habilitar Logfire globalmente
        logfire_config=logfire_config
    )

    # ✅ Detección automática
    logger = AppLogger('production_logger')  # Logfire habilitado automáticamente
    logger.info("Logger configurado con token desde variable de entorno")


def example_without_logfire():
    """Ejemplo sin Logfire para comparar."""
    print("\n=== EJEMPLO SIN LOGFIRE ===")

    # Configurar solo logging tradicional
    setup_logging(
        console_output=True,
        file_output=True,
        enable_logfire=False  # ❌ Sin Logfire
    )

    # ✅ Detección automática - AppLogger detecta que Logfire está deshabilitado
    logger = AppLogger(name='debug_logger')  # Logfire deshabilitado automáticamente

    logger.info("Este logger solo usa logging tradicional")
    logger.warning("No hay Logfire aquí")

    stats = logger.stats()
    print(f"Logfire habilitado: {stats['logfire_enabled']}")
    print(f"Handlers: {[h['type'] for h in stats['handlers']]}")


def example_override_detection():
    """Ejemplo de sobrescribir la detección automática."""
    print("\n=== EJEMPLO DE SOBRESCRIBIR DETECCIÓN AUTOMÁTICA ===")

    # Configurar Logfire globalmente
    setup_logging(
        console_output=True,
        file_output=True,
        enable_logfire=True,  # ✅ Habilitar Logfire globalmente
        logfire_config={
            'service_name': 'dexes-trading-bot',
            'environment': 'development'
        }
    )


def example_complete_configuration():
    """Ejemplo con configuración completa de todos los parámetros."""
    print("\n=== EJEMPLO DE CONFIGURACIÓN COMPLETA ===")

    setup_logging(
        # Configuración de salida
        console_output=True,           # Mostrar logs en consola con colores
        file_output=True,              # Guardar logs en archivo

        # Configuración de archivos
        log_directory="production_logs",  # Directorio personalizado
        log_filename="trading_%Y-%m-%d_%H-%M-%S.log",  # Nombre personalizado

        # Configuración de niveles
        min_level_to_process='INFO',   # Nivel mínimo general
        module_levels={                # Niveles específicos por módulo
            'trading_bot': 'DEBUG',    # Más detallado para trading
            'price_tracker': 'INFO',   # Normal para price tracker
            'wallet_manager': 'WARNING',  # Solo warnings y errores
            'dex_analyzer': 'ERROR'    # Solo errores
        },

        # Configuración de Logfire
        enable_logfire=True,           # Habilitar Logfire globalmente
        logfire_config={
            'service_name': 'dexes-trading-bot',
            'environment': 'production',
            'tags': {
                'project': 'dexes',
                'version': '1.0.0',
                'deployment': 'aws-ec2'
            }
        }
    )

    # ✅ Detección automática
    trading_logger = AppLogger('trading_bot')
    price_logger = AppLogger('price_tracker')
    wallet_logger = AppLogger('wallet_manager')
    analyzer_logger = AppLogger('dex_analyzer')

    # Enviar logs de prueba
    trading_logger.debug("Debug de trading (visible)")
    price_logger.info("Info de price tracker (visible)")
    wallet_logger.warning("Warning de wallet (visible)")
    analyzer_logger.error("Error de analyzer (visible)")

    print("Configuración completa aplicada con éxito")

    # ✅ Detección automática (Logfire habilitado)
    auto_logger = AppLogger('auto_detection')
    
    # ✅ Sobrescribir explícitamente
    forced_disabled_logger = AppLogger('forced_disabled', enable_logfire=False)
    forced_enabled_logger = AppLogger('forced_enabled', enable_logfire=True)

    # Verificar estados
    print(f"Auto detection logger - Logfire: {auto_logger.is_logfire_enabled()}")
    print(f"Forced disabled logger - Logfire: {forced_disabled_logger.is_logfire_enabled()}")
    print(f"Forced enabled logger - Logfire: {forced_enabled_logger.is_logfire_enabled()}")

    # Enviar logs de prueba
    auto_logger.info("Log con detección automática")
    forced_disabled_logger.warning("Log con Logfire forzadamente deshabilitado")
    forced_enabled_logger.error("Log con Logfire forzadamente habilitado")


if __name__ == "__main__":
    main()
    example_detection_automatic()
    example_with_environment_token()
    example_without_logfire()
    example_override_detection()
    example_complete_configuration()
