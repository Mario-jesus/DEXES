# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Dict, List, Any
from solders.pubkey import Pubkey as PublicKey
import base58
import requests

from .wallet_manager import SolanaWalletManager


class SolanaAccountInfo:
    """Consulta de información de cuentas Solana - Balances, tokens, historial"""
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        self.wallet_manager = wallet_manager
        self.client = wallet_manager.client

    def get_balance_info(self, public_key: str) -> Dict[str, Any]:
        """Obtiene información completa de balance incluyendo valor en USD"""
        try:
            # Obtener balance SOL
            sol_balance = self.get_sol_balance(public_key)
            
            # Obtener precio SOL usando Jupiter 2025
            sol_price = self._get_sol_price()
            
            # Calcular valor USD
            usd_value = sol_balance * sol_price if sol_price else 0
            
            balance_info = {
                'address': public_key,
                'sol_balance': sol_balance,
                'sol_price_usd': sol_price,
                'usd_value': usd_value,
                'network': self.wallet_manager.network,
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
                'network': self.wallet_manager.network,
                'error': str(e)
            }

    def _get_sol_price(self) -> float:
        """Obtiene precio SOL usando Jupiter 2025"""
        try:
            url = "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                price = float(data['data']['So11111111111111111111111111111111111111112']['price'])
                return price
            else:
                # Fallback a precio estimado
                return 140.0
                
        except Exception:
            # Precio de emergencia
            return 140.0

    def get_sol_balance(self, public_key: str) -> float:
        """Obtiene el balance de SOL de una wallet"""
        try:
            # Validar dirección usando decodificación base58
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida: longitud incorrecta")
                return 0.0

            pubkey = PublicKey.from_bytes(decoded)
            response = self.client.get_balance(pubkey)

            if response.value is not None:
                sol_balance = response.value / 1_000_000_000
                return sol_balance
            else:
                print("❌ No se pudo obtener el balance")
                return 0.0

        except Exception as e:
            print(f"❌ Error obteniendo balance SOL: {e}")
            return 0.0

    def get_account_info(self, public_key: str) -> Dict[str, Any]:
        """Obtiene información detallada de una cuenta"""
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return {}

            pubkey = PublicKey.from_bytes(decoded)
            account_info = self.client.get_account_info(pubkey)
            balance_info = self.client.get_balance(pubkey)

            info: Dict[str, Any] = {
                'address': public_key,
                'sol_balance': balance_info.value / 1_000_000_000 if balance_info.value else 0,
                'lamports': balance_info.value if balance_info.value else 0,
                'network': self.wallet_manager.network,
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

    def get_token_accounts(self, public_key: str) -> List[Dict[str, Any]]:
        """Obtiene todas las cuentas de tokens SPL de una wallet"""
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return []

            pubkey = PublicKey.from_bytes(decoded)
            token_program_id = PublicKey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            
            # Usar el formato correcto para el filtro
            try:
                from solana.rpc.types import TokenAccountOpts
                opts = TokenAccountOpts(program_id=token_program_id)
                response = self.client.get_token_accounts_by_owner(pubkey, opts)
            except ImportError:
                # Fallback para versiones diferentes
                response = self.client.get_token_accounts_by_owner(pubkey, program_id=token_program_id)

            token_accounts: List[Dict[str, Any]] = []

            if response.value:
                print(f"🪙 Encontradas {len(response.value)} cuentas de tokens:")

                for i, account in enumerate(response.value):
                    # Extraer mint address de los datos de la cuenta
                    mint_address = 'N/A'
                    try:
                        if account.account.data and len(account.account.data) >= 32:
                            # Los primeros 32 bytes son el mint address
                            mint_bytes = bytes(account.account.data[:32])
                            mint_address = base58.b58encode(mint_bytes).decode('utf-8')
                    except Exception as e:
                        print(f"⚠️  Error extrayendo mint: {e}")
                    
                    account_info: Dict[str, Any] = {
                        'account_address': str(account.pubkey),
                        'mint': mint_address,
                        'balance': 0,
                        'decimals': 0
                    }

                    # Obtener balance y decimales
                    try:
                        token_info = self.client.get_token_account_balance(account.pubkey)
                        if token_info.value:
                            account_info.update({
                                'balance': float(token_info.value.ui_amount or 0),
                                'decimals': token_info.value.decimals,
                                'raw_amount': token_info.value.amount
                            })
                    except Exception as e:
                        print(f"⚠️  Error obteniendo balance: {e}")

                    token_accounts.append(account_info)
                    print(f"   {i+1}. Mint: {mint_address}")
                    print(f"      Balance: {account_info['balance']} tokens ({account_info['decimals']} decimales)")
                    print(f"      Cuenta: {str(account.pubkey)}")

            return token_accounts

        except Exception as e:
            print(f"❌ Error obteniendo cuentas de tokens: {e}")
            return []

    def get_token_balance(self, mint_address: str, owner_address: str = None) -> float:
        """Obtiene el balance de un token específico por su mint address"""
        try:
            # Si no se proporciona owner_address, usar la wallet actual
            if not owner_address:
                if not self.wallet_manager.keypair:
                    print("❌ No hay wallet cargada")
                    return 0.0
                owner_address = str(self.wallet_manager.keypair.pubkey())
            
            print(f"🔍 Buscando token {mint_address} en wallet {owner_address[:20]}...")
            
            # Obtener todas las cuentas de tokens del owner
            token_accounts = self.get_token_accounts(owner_address)
            
            # Buscar el token específico por mint
            for account in token_accounts:
                if account['mint'] == mint_address:
                    balance = float(account['balance'])
                    print(f"✅ Token encontrado! Balance: {balance} tokens")
                    return balance
            
            # Si no se encuentra el token, devolver 0
            print(f"❌ Token {mint_address} no encontrado en la wallet")
            return 0.0
            
        except Exception as e:
            print(f"❌ Error obteniendo balance del token: {e}")
            return 0.0

    def get_transaction_history(self, public_key: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtiene el historial de transacciones de una wallet"""
        try:
            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida")
                return []

            pubkey = PublicKey.from_bytes(decoded)
            response = self.client.get_signatures_for_address(pubkey, limit=limit)

            transactions: List[Dict[str, Any]] = []

            if response.value:
                print(f"📜 Últimas {len(response.value)} transacciones:")

                for i, tx in enumerate(response.value):
                    tx_info: Dict[str, Any] = {
                        'signature': str(tx.signature),
                        'slot': tx.slot,
                        'block_time': tx.block_time,
                        'confirmation_status': tx.confirmation_status,
                        'err': tx.err
                    }

                    if tx.block_time:
                        tx_info['datetime'] = datetime.fromtimestamp(tx.block_time).isoformat()

                    transactions.append(tx_info)

                    status = "✅ Exitosa" if not tx.err else "❌ Falló"
                    date_str = tx_info.get('datetime', 'N/A')[:19] if tx_info.get('datetime') else 'N/A'
                    print(f"   {i+1}. {status} - {date_str}")
                    print(f"      Signature: {str(tx.signature)[:20]}...")

            return transactions

        except Exception as e:
            print(f"❌ Error obteniendo historial: {e}")
            return []

    def explain_account_address(self, account_address: str) -> Dict[str, Any]:
        """Explica qué es un account_address y obtiene información detallada"""
        try:
            print(f"🔍 Analizando Account Address: {account_address}")
            print("=" * 60)
            
            # Obtener información de la cuenta
            account_pubkey = PublicKey.from_string(account_address)
            account_info = self.client.get_account_info(account_pubkey)
            
            if not account_info.value:
                print("❌ Cuenta no encontrada")
                return {}
            
            # Extraer información básica
            info = {
                'account_address': account_address,
                'lamports': account_info.value.lamports,
                'owner': str(account_info.value.owner),
                'executable': account_info.value.executable,
                'rent_epoch': account_info.value.rent_epoch,
                'data_length': len(account_info.value.data) if account_info.value.data else 0
            }
            
            print(f"📊 **INFORMACIÓN GENERAL:**")
            print(f"   • Account Address: {account_address}")
            print(f"   • Lamports (rent): {info['lamports']:,}")
            print(f"   • Owner Program: {info['owner']}")
            print(f"   • Ejecutable: {info['executable']}")
            print(f"   • Tamaño datos: {info['data_length']} bytes")
            
            # Si es una cuenta de token SPL
            if info['owner'] == 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA':
                print(f"\n🪙 **ES UNA CUENTA DE TOKEN SPL:**")
                
                # Extraer mint address
                if account_info.value.data and len(account_info.value.data) >= 32:
                    mint_bytes = bytes(account_info.value.data[:32])
                    mint_address = base58.b58encode(mint_bytes).decode('utf-8')
                    info['mint_address'] = mint_address
                    print(f"   • Mint Address: {mint_address}")
                
                # Extraer owner de la cuenta de token (bytes 32-64)
                if len(account_info.value.data) >= 64:
                    owner_bytes = bytes(account_info.value.data[32:64])
                    token_owner = base58.b58encode(owner_bytes).decode('utf-8')
                    info['token_owner'] = token_owner
                    print(f"   • Dueño del Token: {token_owner}")
                
                # Obtener balance
                try:
                    balance_info = self.client.get_token_account_balance(account_pubkey)
                    if balance_info.value:
                        info.update({
                            'balance': float(balance_info.value.ui_amount or 0),
                            'decimals': balance_info.value.decimals,
                            'raw_amount': balance_info.value.amount
                        })
                        print(f"   • Balance: {info['balance']} tokens")
                        print(f"   • Decimales: {info['decimals']}")
                        print(f"   • Raw Amount: {info['raw_amount']}")
                except Exception as e:
                    print(f"   ⚠️  Error obteniendo balance: {e}")
                
                print(f"\n💡 **EXPLICACIÓN:**")
                print(f"   Esta es una 'subcuenta' dentro de tu wallet que almacena")
                print(f"   un token específico. Es como una cuenta bancaria separada")
                print(f"   para cada tipo de moneda que posees.")
                print(f"   ")
                print(f"   • Wallet Principal → Contiene SOL")
                print(f"   • Account Address → Contiene este token específico")
                print(f"   • Mint Address → Identifica QUÉ token es")
            
            else:
                print(f"\n📋 **OTRO TIPO DE CUENTA:**")
                print(f"   Esta no es una cuenta de token SPL estándar.")
                print(f"   Podría ser un programa, NFT, o otro tipo de datos.")
            
            return info
            
        except Exception as e:
            print(f"❌ Error analizando account address: {e}")
            return {}
