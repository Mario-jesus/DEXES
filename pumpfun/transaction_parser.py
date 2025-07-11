# -*- coding: utf-8 -*-
"""
Pump.fun Transaction Parser - Parser asíncrono para transacciones de Pump.fun
Basado en objetos solders para máxima compatibilidad con Solana
"""
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from solana.rpc.async_api import AsyncClient as SolanaAsyncClient
from solders.signature import Signature


@dataclass
class PumpFunTradeInfo:
    """Información estructurada del trade de Pump.fun"""
    signature: str
    slot: int
    block_time: Optional[int]
    trade_type: str
    trader: str
    token_mint: str
    token_amount: float
    sol_amount: float
    fee: float
    success: bool
    compute_units_consumed: Optional[int]
    timestamp: datetime

    def __str__(self):
        return f"""
=== PUMP.FUN TRADE INFO ===
Signature: {self.signature}
Tipo: {self.trade_type.upper()}
Trader: {self.trader}
Token: {self.token_mint}
Cantidad Token: {self.token_amount:,.6f}
Cantidad SOL: {self.sol_amount:.6f}
Fee: {self.fee/1_000_000:.6f} SOL
Éxito: {self.success}
Slot: {self.slot}
Tiempo: {self.block_time}
Compute Units: {self.compute_units_consumed:,}
Timestamp: {self.timestamp}
"""

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la información del trade a diccionario"""
        return {
            'signature': self.signature,
            'slot': self.slot,
            'block_time': self.block_time,
            'trade_type': self.trade_type,
            'trader': self.trader,
            'token_mint': self.token_mint,
            'token_amount': self.token_amount,
            'sol_amount': self.sol_amount,
            'fee': self.fee,
            'success': self.success,
            'compute_units_consumed': self.compute_units_consumed,
            'timestamp': self.timestamp.isoformat()
        }


class PumpFunTransactionParser:
    """Parser asíncrono especializado para transacciones de Pump.fun con objetos solders"""

    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        """
        Inicializa el parser de transacciones
        
        Args:
            rpc_url: URL del RPC de Solana
        """
        self.rpc_url = rpc_url
        self.rpc_client: Optional[SolanaAsyncClient] = None

        print("🔍 Pump.fun Transaction Parser inicializado")
        print(f"🌐 Configurado para conectar a {rpc_url}")

    async def __aenter__(self):
        """Context manager entry - inicializa conexión RPC"""
        print("🔌 Iniciando sesión de Transaction Parser...")
        self.rpc_client = SolanaAsyncClient(self.rpc_url)
        await self.test_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cierra conexión RPC"""
        print("🔌 Cerrando sesión de Transaction Parser...")
        if self.rpc_client:
            await self.rpc_client.close()
            self.rpc_client = None
        print("✅ Sesión de Transaction Parser cerrada correctamente")

    async def test_connection(self) -> bool:
        """
        Prueba la conexión al RPC de Solana
        
        Returns:
            True si la conexión es exitosa, False si no
        """
        try:
            if not self.rpc_client:
                print("❌ Cliente RPC no inicializado")
                return False

            response = await self.rpc_client.get_slot()
            if response.value:
                print(f"✅ Conexión RPC exitosa - Slot actual: {response.value}")
                return True
            else:
                print("❌ No se pudo obtener el slot actual")
                return False
        except Exception as e:
            print(f"❌ Error probando conexión RPC: {e}")
            return False

    async def get_transaction(self, signature: str) -> Optional[Any]:
        """
        Obtiene una transacción desde la blockchain
        
        Args:
            signature: Firma de la transacción
            
        Returns:
            Datos de la transacción o None si hay error
        """
        try:
            if not self.rpc_client:
                print("❌ Cliente RPC no inicializado")
                return None

            sig_obj = Signature.from_string(signature)
            
            response = await self.rpc_client.get_transaction(
                sig_obj,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )

            if response.value:
                print(f"✅ Transacción obtenida: {signature[:8]}...")
                return response.value
            else:
                print(f"❌ No se encontró la transacción: {signature}")
                return None

        except Exception as e:
            print(f"❌ Error obteniendo transacción: {e}")
            return None

    async def parse_transaction(self, tx_data) -> Optional[PumpFunTradeInfo]:
        """
        Parsea una transacción de Pump.fun
        
        Args:
            tx_data: Datos de la transacción desde RPC
            
        Returns:
            Información estructurada del trade o None si hay error
        """
        try:
            # Acceder a atributos directamente
            slot = tx_data.slot
            block_time = getattr(tx_data, 'block_time', None)

            # Acceder a la transacción
            transaction = tx_data.transaction

            # Extraer signature
            if hasattr(transaction, 'transaction') and hasattr(transaction.transaction, 'signatures'):
                signatures = transaction.transaction.signatures
                signature = str(signatures[0]) if signatures else "Unknown"
            else:
                signature = "Unknown"

            # Metadata de la transacción
            meta = transaction.meta if hasattr(transaction, 'meta') and transaction.meta else None

            if meta:
                fee = meta.fee if hasattr(meta, 'fee') else 0
                success = meta.err is None if hasattr(meta, 'err') else True
                compute_units = meta.compute_units_consumed if hasattr(meta, 'compute_units_consumed') else 0
            else:
                fee = 0
                success = True
                compute_units = 0

            # Extraer información del mensaje
            if hasattr(transaction, 'transaction') and hasattr(transaction.transaction, 'message'):
                message = transaction.transaction.message
                account_keys = message.account_keys if hasattr(message, 'account_keys') else []
            else:
                account_keys = []

            # Encontrar el trader (primer account que es signer)
            trader = None
            for account in account_keys:
                if hasattr(account, 'signer') and account.signer:
                    trader = str(account.pubkey)
                    break

            # Analizar los logs para determinar el tipo de operación
            logs = []
            if meta and hasattr(meta, 'log_messages') and meta.log_messages:
                logs = meta.log_messages

            trade_type = self._determine_trade_type(logs)

            # Extraer información de tokens
            token_info = self._extract_token_info(meta)

            # Calcular cantidades de SOL basado en cambios de balance
            sol_amount = self._calculate_sol_amount(meta, account_keys, trader)

            # Crear timestamp
            timestamp = datetime.now()
            if block_time:
                try:
                    timestamp = datetime.fromtimestamp(block_time)
                except:
                    pass

            return PumpFunTradeInfo(
                signature=signature,
                slot=slot,
                block_time=block_time,
                trade_type=trade_type,
                trader=trader or "Unknown",
                token_mint=token_info.get('mint', 'Unknown'),
                token_amount=token_info.get('amount', 0.0),
                sol_amount=sol_amount,
                fee=fee,
                success=success,
                compute_units_consumed=compute_units,
                timestamp=timestamp
            )

        except Exception as e:
            print(f"❌ Error parseando transacción: {e}")
            print(f"Tipo de objeto: {type(tx_data)}")
            return None

    async def parse_transaction_by_signature(self, signature: str) -> Optional[PumpFunTradeInfo]:
        """
        Obtiene y parsea una transacción por su firma
        
        Args:
            signature: Firma de la transacción
            
        Returns:
            Información estructurada del trade o None si hay error
        """
        try:
            # Obtener la transacción
            tx_data = await self.get_transaction(signature)
            if not tx_data:
                return None

            # Parsear la transacción
            return await self.parse_transaction(tx_data)

        except Exception as e:
            print(f"❌ Error parseando transacción por firma: {e}")
            return None

    async def parse_multiple_transactions(self, signatures: List[str]) -> Dict[str, Optional[PumpFunTradeInfo]]:
        """
        Parsea múltiples transacciones de forma concurrente y realmente al mismo tiempo
        
        Args:
            signatures: Lista de firmas de transacciones
            
        Returns:
            Diccionario con resultados: {signature: trade_info}
        """
        results = {}

        try:
            # Crear tareas para procesar transacciones concurrentemente
            tasks = [self.parse_transaction_by_signature(signature) for signature in signatures]

            # Ejecutar todas las tareas al mismo tiempo
            trade_infos = await asyncio.gather(*tasks, return_exceptions=True)

            for signature, trade_info in zip(signatures, trade_infos):
                if isinstance(trade_info, Exception):
                    print(f"❌ Error procesando transacción {signature}: {trade_info}")
                    results[signature] = None
                else:
                    results[signature] = trade_info

            return results

        except Exception as e:
            print(f"❌ Error procesando múltiples transacciones: {e}")
            return results

    def _determine_trade_type(self, logs: list) -> str:
        """Determina si es compra o venta basado en los logs"""
        for log in logs:
            log_str = str(log)
            if "Instruction: Buy" in log_str:
                return "buy"
            elif "Instruction: Sell" in log_str:
                return "sell"
        return "unknown"

    def _extract_token_info(self, meta) -> Dict[str, Any]:
        """Extrae información del token de los balances"""
        token_info = {'mint': 'Unknown', 'amount': 0.0}

        if not meta:
            return token_info

        pre_balances = getattr(meta, 'pre_token_balances', [])
        post_balances = getattr(meta, 'post_token_balances', [])
        
        if pre_balances:
            # Tomar el primer balance de token como referencia
            first_balance = pre_balances[0]
            token_info['mint'] = str(first_balance.mint) if hasattr(first_balance, 'mint') else 'Unknown'

            # Calcular diferencia en cantidad de tokens
            if hasattr(first_balance, 'ui_token_amount'):
                pre_amount = float(first_balance.ui_token_amount.ui_amount or 0)
            else:
                pre_amount = 0.0

            # Buscar el balance post correspondiente
            post_amount = 0.0
            for post_balance in post_balances:
                if hasattr(post_balance, 'account_index') and hasattr(first_balance, 'account_index'):
                    if post_balance.account_index == first_balance.account_index:
                        if hasattr(post_balance, 'ui_token_amount'):
                            post_amount = float(post_balance.ui_token_amount.ui_amount or 0)
                        break

            token_info['amount'] = abs(post_amount - pre_amount)

        return token_info

    def _calculate_sol_amount(self, meta, account_keys: list, trader: str) -> float:
        """Calcula la cantidad de SOL involucrada en el trade"""
        if not meta:
            return 0.0

        pre_balances = getattr(meta, 'pre_balances', [])
        post_balances = getattr(meta, 'post_balances', [])

        if not pre_balances or not post_balances:
            return 0.0

        # Encontrar el índice del trader
        trader_index = None
        for i, account in enumerate(account_keys):
            account_pubkey = str(account.pubkey) if hasattr(account, 'pubkey') else str(account)
            if account_pubkey == trader:
                trader_index = i
                break

        if trader_index is None or trader_index >= len(pre_balances) or trader_index >= len(post_balances):
            return 0.0

        # Calcular diferencia en lamports (excluyendo fee)
        pre_balance = pre_balances[trader_index]
        post_balance = post_balances[trader_index]
        fee = getattr(meta, 'fee', 0)

        # La diferencia real del trade (sin contar el fee)
        lamports_diff = abs(post_balance - pre_balance - fee)

        # Convertir lamports a SOL
        return lamports_diff / 1_000_000_000


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

async def example_usage():
    """Ejemplo de uso del PumpFunTransactionParser"""
    print("🚀 Ejemplo de uso del PumpFunTransactionParser")
    print("=" * 60)

    # Firma de ejemplo (reemplazar con una firma real)
    example_signature = "5mzH9SMCHm5RYkTL1TxrrEqi3oxdtEuLXbkTMrZihYzhihTGN1w7AqXXv5pgCirrLEHuPAoreKcSsoGXs15BSJCS"

    # Usar async with para gestión automática de conexiones
    async with PumpFunTransactionParser() as parser:
        # Verificar conexión
        print("\n📡 Verificando conexión RPC...")
        if not await parser.test_connection():
            print("❌ No se pudo conectar al RPC")
            return

        # Parsear una transacción individual
        print(f"\n🔍 Parseando transacción: {example_signature[:8]}...")
        trade_info = await parser.parse_transaction_by_signature(example_signature)

        if trade_info:
            print("✅ Transacción parseada exitosamente:")
            print(trade_info)
        else:
            print("❌ No se pudo parsear la transacción")


if __name__ == "__main__":
    # Ejecutar ejemplo
    asyncio.run(example_usage())
