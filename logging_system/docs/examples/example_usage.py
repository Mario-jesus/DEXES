# -*- coding: utf-8 -*-
"""
Ejemplo de uso del sistema de logging integrado con Logfire.
Usando la configuración centralizada desde logger_config.
"""
import os
from logging_system import setup_logging, AppLogger

def main():
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
        console_output=True,
        file_output=True,
        min_level_to_process='DEBUG',
        module_levels={
            'trading_bot': 'INFO',
            'price_tracker': 'DEBUG'
        },
        enable_logfire=True,  # Habilitar Logfire globalmente
        logfire_config=logfire_config  # Configuración de Logfire
    )

    # Crear logger (Logfire ya está configurado globalmente)
    logger = AppLogger(
        name='trading_bot',
        enable_logfire=True,  # Añadir Logfire a este logger específico
        logfire_config={'tags': {'component': 'trading_bot'}}  # Tags adicionales
    )

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


def example_with_environment_token():
    """Ejemplo usando token desde variable de entorno."""
    print("\n=== Ejemplo con Token desde Variable de Entorno ===")

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
        enable_logfire=True,
        logfire_config=logfire_config
    )

    logger = AppLogger('production_logger', enable_logfire=True)
    logger.info("Logger configurado con token desde variable de entorno")


def example_without_logfire():
    """Ejemplo sin Logfire para comparar."""
    print("\n=== Ejemplo sin Logfire ===")

    # Configurar solo logging tradicional
    setup_logging(
        console_output=True,
        file_output=True,
        enable_logfire=False  # Sin Logfire
    )

    # Crear logger sin Logfire
    logger = AppLogger(
        name='debug_logger',
        enable_logfire=False
    )

    logger.info("Este logger solo usa logging tradicional")
    logger.warning("No hay Logfire aquí")

    stats = logger.stats()
    print(f"Logfire habilitado: {stats['logfire_enabled']}")
    print(f"Handlers: {[h['type'] for h in stats['handlers']]}")


if __name__ == "__main__":
    main()
    example_with_environment_token()
    example_without_logfire()
