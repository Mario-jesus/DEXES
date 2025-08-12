# -*- coding: utf-8 -*-
from typing import Optional, TypedDict, NotRequired, List
from solders.keypair import Keypair
from decimal import Decimal, getcontext
import asyncio

from pumpfun.transactions import PumpFunTransactions, TradeAction, PoolType
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData

getcontext().prec = 18

class TradeParams(TypedDict):
    mint: str
    action: NotRequired[TradeAction]
    amount: NotRequired[str]
    denominated_in_sol: NotRequired[bool]
    slippage: NotRequired[str]
    priority_fee: NotRequired[str]
    pool: NotRequired[PoolType]


async def load_wallet(wallet_file: str) -> Optional[WalletData]:
    async with PumpFunWalletStorage() as wallet_storage:
        wallet = await wallet_storage.load_wallet_data_from_file(wallet_file)
        return wallet


async def create_local_trade(transactions: PumpFunTransactions,
                                keypair: Keypair,
                                trade_params: TradeParams,
                                rpc_endpoint: str = "https://api.mainnet-beta.solana.com/"):
        try:
            if "action" not in trade_params or "amount" not in trade_params:
                raise ValueError("Action and amount are required")

            return await transactions.create_and_send_local_trade(
                keypair=keypair,
                action=trade_params["action"],
                mint=trade_params["mint"],
                amount=trade_params["amount"],
                denominated_in_sol=trade_params.get("denominated_in_sol", True),
                slippage=trade_params.get("slippage", "15.0"),
                priority_fee=trade_params.get("priority_fee", "0.00001"),
                pool=trade_params.get("pool", "auto"),
                rpc_endpoint=rpc_endpoint
            )
        except Exception as e:
            print(f"Error creating local trade: {e}")
            return None


async def create_local_liquidation(transactions: PumpFunTransactions,
                                    keypair: Keypair,
                                    trade_params: TradeParams,
                                    rpc_endpoint: str = "https://api.mainnet-beta.solana.com/"):
    try:
        return await transactions.create_and_send_local_trade(
            keypair=keypair,
            action="sell",
            mint=trade_params["mint"],
            amount=trade_params.get("amount", "100%"),
            denominated_in_sol=False,
            slippage=trade_params.get("slippage", "15.0"),
            priority_fee=trade_params.get("priority_fee", "0.00001"),
            pool=trade_params.get("pool", "auto"),
            rpc_endpoint=rpc_endpoint
        )
    except Exception as e:
        print(f"Error creating local liquidation: {e}")
        return None


async def execute_trading(
        transactions: PumpFunTransactions,
        wallet: WalletData,
        mint: str,
        available_capital: str,
        order_size: Optional[str] = None,
        iterations: Optional[int] = None,
        delay: int = 10
    ):
    signatures: List[str] = []

    # Convertir available_capital a Decimal para cálculos precisos
    total_capital = Decimal(available_capital)
    remaining_capital = total_capital

    iteracion_actual = 0

    # Determinar el modo de operación y calcular el monto por iteración
    if iterations is not None:
        # Modo por iteraciones: repartir el capital total entre las iteraciones
        amount_per_iteration = total_capital / Decimal(iterations)
        remaining_iterations = iterations
    elif order_size is not None:
        # Modo por order_size: usar el order_size especificado
        amount_per_iteration = Decimal(order_size)
        # Calcular cuántas iteraciones podemos hacer con el capital disponible
        remaining_iterations = int(total_capital / amount_per_iteration)
    else:
        # Sin configuración específica: usar todo el capital en una sola transacción
        amount_per_iteration = total_capital
        remaining_iterations = 1

    while remaining_iterations > 0 and remaining_capital > Decimal("0"):
        # Calcular el monto para esta iteración
        if iterations is not None:
            # Modo por iteraciones: usar el monto calculado al inicio
            amount = amount_per_iteration
        else:
            # Modo por order_size o sin configuración: usar el monto calculado al inicio
            amount = amount_per_iteration

        # Verificar que no excedamos el capital restante
        if amount > remaining_capital:
            amount = remaining_capital
            
        # Si no hay monto disponible, terminar
        if amount <= Decimal("0"):
            break

        trade_params = TradeParams(
            action="buy",
            mint=mint,
            amount=format(amount, "f"),
            denominated_in_sol=True,
            slippage="15.0",
            priority_fee="0.00001",
            pool="auto"
        )

        try:
            keypair = wallet.get_keypair()
        except Exception as e:
            break

        trade = await create_local_trade(
            transactions=transactions,
            keypair=keypair,
            trade_params=trade_params
        )

        if trade:
            signatures.append(trade)
            # Actualizar el capital restante después de una transacción exitosa
            remaining_capital -= amount
        else:
            # Si falla la transacción, no actualizar el capital pero continuar
            pass

        # Actualizar contadores
        remaining_iterations -= 1
        iteracion_actual += 1
        
        # Verificar si debemos continuar después de actualizar
        if remaining_iterations <= 0:
            break
        elif remaining_capital <= Decimal("0"):
            break

        await asyncio.sleep(delay)

    return signatures


async def main():
    wallet = await load_wallet("wallets/wallet_pumpfun.json")
    if not wallet:
        print("Wallet not found")
        return

    async with PumpFunTransactions(api_key=wallet.api_key) as transactions:
        await execute_trading(
            transactions=transactions,
            wallet=wallet,
            mint="6F6jjd71nbjwUZNi93wpXimbyH12CLkeMNJ6X1brpump",
            available_capital="0.00577",
            iterations=10,
            delay=10
        )

if __name__ == "__main__":
    asyncio.run(main())
