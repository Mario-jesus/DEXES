# -*- coding: utf-8 -*-
"""
Script para Liquidar Todas las Posiciones de Tokens de una Wallet de Solana.
"""
import asyncio
import sys
import os
from pathlib import Path
from solders.keypair import Keypair

# Agregar el directorio raíz del proyecto al path de Python
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from solana_manager.account_info import SolanaAccountInfo
from pumpfun.transactions import PumpFunTransactions
from pumpfun.api_client import PumpFunApiClient
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData

# --- Configuración ---
# Lee la ruta del archivo de la wallet desde las variables de entorno
WALLET_FILE_PATH = "wallets/wallet_pumpportal.json"
# --- Fin de la Configuración ---


async def liquidate_all_tokens(wallet_address: str, keypair: Keypair = None, api_key: str = None, test_mode: bool = False):
    """
    Obtiene todas las posiciones de tokens de una wallet y vende el 100% de cada una
    de forma concurrente.
    """
    print(f"🌊 Iniciando liquidación para la wallet: {wallet_address}")

    # 1. Obtener todas las cuentas de tokens
    async with SolanaAccountInfo() as account_info:
        token_accounts = await account_info.get_token_accounts(wallet_address)

    if not token_accounts:
        print("🤷 No se encontraron cuentas de tokens para liquidar.")
        return

    # Filtrar tokens con balance cero y posibles tokens conocidos que no quieres vender (ej. USDC)
    positions_to_liquidate = [
        acc for acc in token_accounts if acc.get('balance', 0) > 0
    ]

    if not positions_to_liquidate:
        print("✅ Todas las posiciones de tokens encontradas tienen balance cero o están en la lista de exclusión.")
        return

    print(f"🔥 Se encontraron {len(positions_to_liquidate)} posiciones de tokens con balance para liquidar:")
    for pos in positions_to_liquidate:
        print(f"  -> Mint: {pos['mint']}, Balance: {pos['balance']}")

    # 2. Crear tareas de venta
    api_client = PumpFunApiClient(api_key=api_key)
    async with PumpFunTransactions(api_client=api_client) as tx_manager:
        sell_tasks = []
        for position in positions_to_liquidate:
            mint_address = position['mint']
            print(f"🔫 Preparando liquidación para el token: {mint_address}")

            # Elige el método de transacción basado en las credenciales proporcionadas
            task = None
            if test_mode:
                print("🛑 Modo de prueba activado. No se ejecutarán transacciones reales.")
                print(position)
                print(
                    f"keypair: {keypair}",
                    f"action: sell",
                    f"mint: {mint_address}",
                    f"amount: 100%",
                    f"denominated_in_sol: True",
                    f"slippage: 20",
                    f"priority_fee: 0.00005",
                    sep="\n"
                )
                continue
            elif keypair:
                # Usar firma local (más seguro)
                task = tx_manager.create_and_send_local_trade(
                    keypair=keypair,
                    action="sell",
                    mint=mint_address,
                    amount="100%",  # Vender la totalidad de los tokens
                    denominated_in_sol=True,
                    slippage=20,  # Deslizamiento del 5% (ajustar si es necesario)
                    priority_fee=0.00005,  # Tarifa de prioridad (ajustar si es necesario)
                )
            elif api_key:
                # Usar transacción Lightning de PumpFun
                task = tx_manager.execute_lightning_trade(
                    action="sell",
                    mint=mint_address,
                    amount="100%",
                    denominated_in_sol=True,
                    slippage=20,
                    priority_fee=0.00005,
                )

            if task:
                sell_tasks.append(task)

        if not sell_tasks:
            print("🛑 No se pudieron crear tareas de liquidación. Verifica tu configuración.")
            return

        # 3. Ejecutar todas las tareas de venta de forma concurrente
        print(f"\n🚀 Ejecutando {len(sell_tasks)} liquidaciones concurrentemente...")
        results = await asyncio.gather(*sell_tasks, return_exceptions=True)

        print("\n🏁 Resultados de la liquidación:")
        for i, result in enumerate(results):
            mint = positions_to_liquidate[i]['mint']
            if isinstance(result, Exception):
                print(f"  ❌ Error liquidando {mint}: {result}")
            else:
                print(f"  ✅ Éxito liquidando {mint}. Firma de la transacción: {result}")


async def main():
    """Función principal para configurar y ejecutar el script."""
    if not WALLET_FILE_PATH:
        print("🛑 Error: Falta la variable de entorno 'WALLET_FILE_PATH'.")
        print("   Por favor, configúrala en tu archivo .env para apuntar a tu archivo de wallet JSON.")
        return

    keypair = None
    api_key = None
    public_key = None

    try:
        # Usar PumpFunWalletStorage para cargar los datos de la wallet
        print(f"📂 Cargando datos de la wallet desde: {WALLET_FILE_PATH}")
        wallet_data = await PumpFunWalletStorage.load_wallet_data_from_file(WALLET_FILE_PATH)

        if not wallet_data or not isinstance(wallet_data, WalletData):
            print(f"❌ No se pudieron cargar los datos de la wallet desde {WALLET_FILE_PATH}.")
            return

        print("✅ Wallet cargada exitosamente.")

        # Obtener credenciales desde WalletData
        public_key = wallet_data.wallet_public_key
        api_key = wallet_data.api_key
        keypair = wallet_data.get_keypair()

    except Exception as e:
        print(f"❌ Error crítico al cargar la wallet: {e}")
        return

    if not public_key:
        print("🛑 Error: No se pudo determinar la clave pública de la wallet.")
        return

    await liquidate_all_tokens(public_key, keypair=keypair, api_key=api_key, test_mode=True)


if __name__ == "__main__":
    # Nota: En Windows, puede que necesites configurar la política de eventos de asyncio
    # si encuentras un `RuntimeError: Event loop is closed`.
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
