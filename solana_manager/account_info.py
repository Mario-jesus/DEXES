# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Dict, List, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey as PublicKey
import base58
import aiohttp
import asyncio


class SolanaAccountInfo:
    """Consulta de información de cuentas Solana - Balances, tokens, historial (Asíncrono)"""

    def __init__(self, network: str = 'mainnet-beta', rpc_url: str = 'https://api.mainnet-beta.solana.com'):
        self.network = network
        self.rpc_url = rpc_url
        self.client: Optional[AsyncClient] = None
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Inicializa el cliente AsyncClient y la sesión HTTP."""
        self.client = AsyncClient(self.rpc_url)
        is_connected = await self.client.is_connected()
        if is_connected:
            print(f"🌐 Conectado a Solana {self.network} (RPC: {self.rpc_url})")
        else:
            print(f"🔌 No se pudo conectar a Solana {self.network}. Por favor, verifica la RPC URL.")
            raise Exception("No se pudo conectar a la red Solana")
        
        await self._get_http_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra el cliente AsyncClient y la sesión HTTP."""
        if self.client:
            await self.client.close()
            self.client = None
        await self.close_http_session()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Inicializa y retorna una sesión aiohttp."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close_http_session(self):
        """Cierra la sesión aiohttp si está abierta."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def get_balance_info(self, public_key: str) -> Dict[str, Any]:
        """Obtiene información completa de balance incluyendo valor en USD"""
        try:
            # Obtener balance SOL y precio en paralelo
            sol_balance_task = self.get_sol_balance(public_key)
            sol_price_task = self.get_sol_price()
            
            sol_balance, sol_price = await asyncio.gather(sol_balance_task, sol_price_task)
            
            # Calcular valor USD
            usd_value = sol_balance * sol_price if sol_price else 0
            
            balance_info = {
                'address': public_key,
                'sol_balance': sol_balance,
                'sol_price_usd': sol_price,
                'usd_value': usd_value,
                'network': self.network,
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"📊 Balance completo:")
            print(f"   📍 Dirección: {public_key}")
            print(f"   💰 Balance SOL: {sol_balance:.6f} SOL")
            print(f"   💵 Precio SOL: ${sol_price:.2f} USD")
            print(f"   💸 Valor total: ${usd_value:.2f} USD")
            
            return balance_info
            
        except Exception as e:
            print(f"❌ Error obteniendo balance completo: {e}")
            return {
                'address': public_key,
                'sol_balance': 0.0,
                'sol_price_usd': 0.0,
                'usd_value': 0.0,
                'network': self.network,
                'error': str(e)
            }
        finally:
            await self.close_http_session()

    async def get_sol_price(self) -> float:
        """Obtiene precio SOL usando Jupiter 2025 de forma asíncrona"""
        session = await self._get_http_session()
        SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
        JUPITER_LITE_API = "https://lite-api.jup.ag/price/v3"
        ENDPOINT_PRICE = "/price/v3"
        try:
            url = f"{JUPITER_LITE_API}{ENDPOINT_PRICE}?ids={SOL_MINT_ADDRESS}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data.get(SOL_MINT_ADDRESS, {}).get('usdPrice', 0))
                    return price
                else:
                    return 140.0
                
        except Exception:
            return 140.0

    async def get_sol_balance(self, public_key: str) -> float:
        """Obtiene el balance de SOL de una wallet de forma asíncrona"""
        if not self.client:
            print("❌ Cliente no conectado. Usa 'async with SolanaAccountInfo() as account_info:' para conectar.")
            return 0.0
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida: longitud incorrecta")
                return 0.0

            pubkey = PublicKey.from_bytes(decoded)
            response = await self.client.get_balance(pubkey)

            if response.value is not None:
                return response.value / 1_000_000_000
            else:
                print("❌ No se pudo obtener el balance")
                return 0.0

        except Exception as e:
            print(f"❌ Error obteniendo balance SOL: {e}")
            return 0.0

    async def get_account_info(self, public_key: str) -> Dict[str, Any]:
        """Obtiene información detallada de una cuenta de forma asíncrona"""
        if not self.client:
            print("❌ Cliente no conectado. Usa 'async with SolanaAccountInfo() as account_info:' para conectar.")
            return {}
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return {}

            pubkey = PublicKey.from_bytes(decoded)
            
            # Ejecutar llamadas en paralelo
            account_info_task = self.client.get_account_info(pubkey)
            balance_info_task = self.client.get_balance(pubkey)
            account_info, balance_info = await asyncio.gather(account_info_task, balance_info_task)

            info: Dict[str, Any] = {
                'address': public_key,
                'sol_balance': balance_info.value / 1_000_000_000 if balance_info.value else 0,
                'lamports': balance_info.value if balance_info.value else 0,
                'network': self.network,
                'exists': account_info.value is not None,
                'timestamp': datetime.now().isoformat()
            }

            if account_info.value:
                info.update({
                    'executable': account_info.value.executable,
                    'owner': str(account_info.value.owner),
                    'rent_epoch': account_info.value.rent_epoch,
                    'data_length': len(account_info.value.data) if account_info.value.data else 0
                })

            print("📊 Información de cuenta:")
            print(f"   📍 Dirección: {info['address']}")
            print(f"   💰 Balance SOL: {info['sol_balance']:.9f}")
            print(f"   🏦 Lamports: {info['lamports']:,}")
            print(f"   ✅ Existe: {info['exists']}")

            return info

        except Exception as e:
            print(f"❌ Error obteniendo información de cuenta: {e}")
            return {}

    async def get_token_accounts(self, public_key: str) -> List[Dict[str, Any]]:
        """Obtiene todas las cuentas de tokens SPL de una wallet (via RPC jsonParsed)."""
        try:
            # Validación básica de la dirección (opcional, solo para feedback temprano)
            try:
                decoded = base58.b58decode(public_key)
                if len(decoded) != 32:
                    print("❌ Dirección inválida")
                    return []
            except Exception:
                # Si la decodificación falla, el RPC igual puede devolver error entendible
                pass

            session = await self._get_http_session()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    public_key,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"commitment": "finalized", "encoding": "jsonParsed"},
                ],
            }

            async with session.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                # Evitar pasar None como content_type para mantener tipos estrictos
                data = await response.json()

            if "error" in data and data["error"]:
                err = data["error"]
                print(f"❌ Error RPC getTokenAccountsByOwner: {err.get('message', 'Unknown error')}")
                return []

            result = data.get("result", {})
            value = result.get("value", []) or []

            token_accounts: List[Dict[str, Any]] = []
            for entry in value:
                try:
                    account = (entry or {}).get("account", {})
                    parsed = (account.get("data", {}) or {}).get("parsed", {})
                    info = parsed.get("info", {})
                    token_amount = info.get("tokenAmount", {}) or {}

                    pubkey = (entry or {}).get("pubkey", "")
                    mint = info.get("mint", "")
                    decimals = token_amount.get("decimals", 0) or 0
                    ui_amount = token_amount.get("uiAmount", 0.0) or 0.0
                    amount_raw = token_amount.get("amount", "0") or "0"

                    token_accounts.append({
                        'account_address': str(pubkey),
                        'mint': str(mint),
                        'balance': float(ui_amount),
                        'decimals': int(decimals),
                        'raw_amount': str(amount_raw),
                    })
                except Exception as e:
                    print(f"⚠️ Error parseando token account: {e}")
                    continue

            if token_accounts:
                print(f"🪙 Encontradas {len(token_accounts)} cuentas de tokens")

            return token_accounts

        except Exception as e:
            print(f"❌ Error obteniendo cuentas de tokens: {e}")
            return []

    async def get_token_balance(self, mint_address: str, owner_address: Optional[str] = None) -> float:
        """Obtiene el balance total de un token por mint sin depender de solana_rcp"""
        try:
            if not owner_address:
                print("⚠️ No owner_address provided, cannot determine token balance.")
                return 0.0

            token_accounts = await self.get_token_accounts(owner_address)
            total_balance = 0.0
            for acc in token_accounts:
                try:
                    if acc.get('mint') == mint_address:
                        total_balance += float(acc.get('balance', 0.0) or 0.0)
                except Exception:
                    continue

            if total_balance > 0.0:
                print(f"✅ Token encontrado! Balance total: {total_balance} tokens")
            else:
                print(f"❌ Token {mint_address} no encontrado en la wallet")

            return total_balance

        except Exception as e:
            print(f"❌ Error obteniendo balance del token: {e}")
            return 0.0

    async def get_transaction_history(self, public_key: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtiene el historial de transacciones de una wallet de forma asíncrona"""
        if not self.client:
            print("❌ Cliente no conectado. Usa 'async with SolanaAccountInfo() as account_info:' para conectar.")
            return []
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return []

            pubkey = PublicKey.from_bytes(decoded)
            response = await self.client.get_signatures_for_address(pubkey, limit=limit)

            transactions: List[Dict[str, Any]] = []

            if response.value:
                print(f"📜 Últimas {len(response.value)} transacciones:")
                for i, tx_info in enumerate(response.value):
                    tx_details = {
                        'signature': str(tx_info.signature),
                        'block_time': datetime.fromtimestamp(tx_info.block_time) if tx_info.block_time else 'N/A',
                        'memo': tx_info.memo,
                        'slot': tx_info.slot,
                        'error': bool(tx_info.err),
                        'confirmation_status': tx_info.confirmation_status
                    }
                    transactions.append(tx_details)
                    print(f"   {i+1}. Sig: {tx_details['signature'][:30]}... | Status: {tx_details['confirmation_status']}")
            
            return transactions

        except Exception as e:
            print(f"❌ Error obteniendo historial de transacciones: {e}")
            return []

    async def explain_account_address(self, account_address: str) -> Dict[str, Any]:
        """Explica qué tipo de cuenta es (usuario, token, programa, etc.) de forma asíncrona"""
        if not self.client:
            print("❌ Cliente no conectado. Usa 'async with SolanaAccountInfo() as account_info:' para conectar.")
            return {}
        try:
            pubkey = PublicKey.from_string(account_address)
            account_info = await self.client.get_account_info(pubkey)

            if not account_info.value:
                return {'type': 'Not Found', 'message': 'La cuenta no existe en la red.'}

            owner = str(account_info.value.owner)
            is_executable = account_info.value.executable

            explanation = {
                'address': account_address,
                'owner': owner,
                'is_executable': is_executable,
                'rent_epoch': account_info.value.rent_epoch,
                'data_length': len(account_info.value.data)
            }

            # Lógica de identificación
            if owner == "11111111111111111111111111111111":
                explanation['type'] = 'System Program Owned (User Wallet)'
                explanation['message'] = 'Esta es una wallet de usuario estándar.'
            elif owner == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
                explanation['type'] = 'Token Account'
                explanation['message'] = 'Esta es una cuenta que almacena tokens SPL.'
                # Intentar obtener el mint
                if len(account_info.value.data) >= 32:
                    mint_address = base58.b58encode(bytes(account_info.value.data[:32])).decode('utf-8')
                    explanation['token_mint'] = mint_address
            elif is_executable:
                explanation['type'] = 'Program'
                explanation['message'] = 'Esta es una cuenta de un programa (contrato inteligente).'
            else:
                explanation['type'] = 'Data Account'
                explanation['message'] = f'Esta es una cuenta de datos propiedad del programa: {owner}.'

            print(f"🔍 Análisis de cuenta {account_address[:10]}...:")
            print(f"   - Tipo: {explanation['type']}")
            print(f"   - Propietario: {explanation['owner'][:10]}...")
            
            return explanation

        except Exception as e:
            return {'type': 'Error', 'message': str(e)}
