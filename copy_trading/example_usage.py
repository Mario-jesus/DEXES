#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejemplo de uso del sistema CopyTradingMini
"""
import asyncio

from copy_trading.core import CopyTrading
from copy_trading.config import CopyTradingConfig


async def main():
    """Función principal para ejecutar el sistema."""
    # 1. Configurar la wallet (crea una de prueba si no existe)
    wallet_file = "wallets/wallet_pumpportal.json"

    # 2. Definir los traders a seguir
    # Reemplaza estas direcciones con las wallets de los traders que quieres copiar
    traders_to_copy = [
        "4pUQS4sV2V2igHarz515NSAx4t4A2aB8kE7wD4gA3a2Z", # Ejemplo de trader 1
        "7x1aA2sV3V3igHarz515NSAx4t4A2aB8kE7wD4gA3a3W", # Ejemplo de trader 2
        "A1Uh8udZg2CMHS5kKeQouYRGfiAxJ7MYMuRbAz913hJX", # Ejemplo de trader 3
    ]

    # 3. Crear la configuración del sistema
    config = CopyTradingConfig(
        traders=traders_to_copy,
        wallet_file=wallet_file,

        # Modo de copia: 'percentage', 'fixed', 'exact'
        amount_mode="fixed", 
        amount_value=0.001,  # Para 'fixed', es la cantidad de SOL a usar por trade

        # Tipo de transacción: 'local_trade' o 'lightning_trade'
        transaction_type="local_trade",  # Recomendado para mayor control

        # Pool de liquidez: 'auto', 'pump', 'raydium', etc.
        pool_type="auto",

        # -- Parámetros avanzados (opcional) --
        # En modo 'loose', las validaciones que fallen solo mostrarán un warning
        strict_mode=True, 

        # Máximo 0.01 SOL por posición
        max_position_size=0.01,

        # Deslizamiento (slippage) del 15%
        slippage_tolerance=0.15, 

        # Tarifa de prioridad para acelerar transacciones
        priority_fee_sol=0.0005,

        # URL de RPC de Solana. Puedes usar una privada para mejor rendimiento.
        rpc_url="https://api.mainnet-beta.solana.com/",

        # Configuraciones adicionales para Lightning Trade (solo si transaction_type="lightning_trade")
        skip_preflight=True,  # Omite simulación previa
        jito_only=False,      # Usar solo Jito para envío

        # Modo de prueba: no ejecuta trades reales, solo simula
        dry_run=True
    )

    # 4. Crear una instancia del sistema
    # El API key es REQUERIDO para Lightning Trade, opcional para Local Trade
    api_key = None

    if config.transaction_type == "lightning_trade" and not api_key:
        print("⚠️ ADVERTENCIA: Lightning Trade requiere API key.")
        print("   Configura la variable de entorno PUMPFUN_API_KEY")
        print("   o cambia a transaction_type='local_trade'")
        return

    system = CopyTrading(config=config, api_key=api_key)

    # 5. Iniciar el sistema en un bloque `async with` para gestión automática
    try:
        async with system:
            print(f"\n✅ Sistema iniciado (Modo: {config.transaction_type})")
            print("Presiona Ctrl+C para detener.")

            # Mostrar información de la configuración
            print(f"\n📋 Configuración actual:")
            print(f"   - Tipo de transacción: {config.transaction_type}")
            print(f"   - Pool: {config.pool_type}")
            print(f"   - Slippage: {config.slippage_tolerance*100}%")
            print(f"   - Priority Fee: {config.priority_fee_sol} SOL")
            if config.transaction_type == "lightning_trade":
                print(f"   - Skip Preflight: {config.skip_preflight}")
                print(f"   - Jito Only: {config.jito_only}")

            # El sistema ahora está corriendo en segundo plano.
            # Podemos interactuar con él si es necesario.
            # Por ejemplo, para ver métricas cada 10 minutos:
            while system.is_running:
                await asyncio.sleep(600)
                metrics = await system.get_metrics()
                print("\n--- Métricas del Sistema ---")
                print(f"  - Tiempo activo: {metrics['system_metrics']['uptime_seconds']:.0f}s")
                print(f"  - Trades recibidos: {metrics['callback_stats']['trades_received']}")
                print(f"  - Trades en cola: {metrics['queue_stats']['pending_count']}")
                print(f"  - Trades ejecutados: {metrics['system_metrics']['trades_executed']}")
                print(f"  - Balance actual: {metrics['wallet_balance']:.6f} SOL")
                print(f"  - Tipo de transacción: {config.transaction_type}")
                print("--------------------------\n")

    except asyncio.CancelledError:
        print("\nTarea cancelada.")
    except KeyboardInterrupt:
        print("\nInterrupción del usuario detectada.")
    finally:
        print("\n🔌 Deteniendo el sistema...")
        # El bloque `async with` llamará a `system.stop()` automáticamente.

    print("🏁 Sistema detenido.")


if __name__ == "__main__":
    # Nota: Es recomendable configurar un logger para ver todos los detalles.
    # Por defecto, se imprimirán en consola los eventos importantes.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nPrograma terminado.")
