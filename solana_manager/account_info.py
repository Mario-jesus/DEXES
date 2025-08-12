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
            sol_price_task = self._get_sol_price()
            
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

    async def _get_sol_price(self) -> float:
        """Obtiene precio SOL usando Jupiter 2025 de forma asíncrona"""
        session = await self._get_http_session()
        try:
            url = "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['data']['So11111111111111111111111111111111111111112']['price'])
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
        """Obtiene todas las cuentas de tokens SPL de una wallet de forma asíncrona"""
        if not self.client:
            print("❌ Cliente no conectado. Usa 'async with SolanaAccountInfo() as account_info:' para conectar.")
            return []
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return []

            pubkey = PublicKey.from_bytes(decoded)
            token_program_id = PublicKey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            
            from solana.rpc.types import TokenAccountOpts
            opts = TokenAccountOpts(program_id=token_program_id)
            response = await self.client.get_token_accounts_by_owner(pubkey, opts)

            token_accounts: List[Dict[str, Any]] = []

            if response.value:
                print(f"🪙 Encontradas {len(response.value)} cuentas de tokens")

                balance_tasks = []
                for account in response.value:
                    mint_address = 'N/A'
                    try:
                        if account.account.data and len(account.account.data) >= 32:
                            mint_bytes = bytes(account.account.data[:32])
                            mint_address = base58.b58encode(mint_bytes).decode('utf-8')
                    except Exception as e:
                        print(f"⚠️  Error extrayendo mint: {e}")
                    
                    account_info = {
                        'account_address': str(account.pubkey),
                        'mint': mint_address,
                    }
                    token_accounts.append(account_info)
                    balance_tasks.append(self.client.get_token_account_balance(account.pubkey))

                # Obtener balances en paralelo
                balances = await asyncio.gather(*balance_tasks, return_exceptions=True)

                for i, result in enumerate(balances):
                    if isinstance(result, Exception):
                        print(f"⚠️ Error obteniendo balance para cuenta {token_accounts[i]['account_address']}: {result}")
                        token_accounts[i].update({'balance': 0, 'decimals': 0, 'raw_amount': '0'})
                    else:
                        token_accounts[i].update({
                            'balance': float(result.value.ui_amount or 0),
                            'decimals': result.value.decimals,
                            'raw_amount': result.value.amount
                        })
                    
                    #print(f"   {i+1}. Mint: {token_accounts[i]['mint']}")
                    #print(f"      Balance: {token_accounts[i]['balance']} tokens ({token_accounts[i]['decimals']} decimales)")
                    #print(f"      Cuenta: {token_accounts[i]['account_address']}")

            return token_accounts

        except Exception as e:
            print(f"❌ Error obteniendo cuentas de tokens: {e}")
            return []

    async def get_token_balance(self, mint_address: str, owner_address: str = None) -> float:
        """Obtiene el balance de un token específico por su mint address de forma asíncrona"""
        try:
            if not owner_address:
                # This part of the original code relied on self.wallet_manager.keypair
                # which is no longer available. Assuming a default or that this
                # function will be refactored to accept a keypair directly.
                # For now, we'll just print a warning and return 0.
                print("⚠️ No owner_address provided, cannot determine token balance.")
                return 0.0
            
            print(f"🔍 Buscando token {mint_address} en wallet {owner_address[:20]}...")
            
            token_accounts = await self.get_token_accounts(owner_address)
            
            for account in token_accounts:
                if account['mint'] == mint_address:
                    balance = float(account['balance'])
                    print(f"✅ Token encontrado! Balance: {balance} tokens")
                    return balance
            
            print(f"❌ Token {mint_address} no encontrado en la wallet")
            return 0.0
            
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
