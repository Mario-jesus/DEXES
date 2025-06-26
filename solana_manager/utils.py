# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Dict, Any
import base58

from .wallet_manager import SolanaWalletManager


class SolanaUtils:
    """Utilidades para trabajar con Solana - Validación, conversiones, información de red"""
    
    def __init__(self, wallet_manager: SolanaWalletManager = None):
        self.wallet_manager = wallet_manager
        self.client = wallet_manager.client if wallet_manager else None

    def validate_address(self, address: str) -> bool:
        """Valida si una dirección de Solana es válida"""
        try:
            if not address or len(address) < 32 or len(address) > 44:
                print("❌ Dirección inválida: longitud incorrecta")
                return False

            decoded = base58.b58decode(address)
            if len(decoded) != 32:
                print("❌ Dirección inválida: debe tener 32 bytes")
                return False

            print(f"✅ Dirección válida: {address[:20]}...")
            return True

        except Exception as e:
            print(f"❌ Dirección inválida: {e}")
            return False

    def get_network_info(self) -> Dict[str, Any]:
        """Obtiene información de la red Solana"""
        try:
            if not self.wallet_manager or not self.client:
                print("❌ No hay conexión a la red configurada")
                return {}
                
            slot = self.client.get_slot()

            info = {
                'network': self.wallet_manager.network,
                'rpc_url': self.wallet_manager.rpc_urls[self.wallet_manager.network],
                'current_slot': slot.value if slot.value else 0,
                'status': 'connected',
                'timestamp': datetime.now().isoformat()
            }

            print("🌐 Información de red:")
            print(f"   Red: {info['network']}")
            print(f"   Slot actual: {info['current_slot']:,}")
            print(f"   Estado: {info['status']}")

            return info

        except Exception as e:
            print(f"❌ Error obteniendo info de red: {e}")
            return {}

    def convert_lamports_to_sol(self, lamports: int) -> float:
        """Convierte lamports a SOL"""
        return lamports / 1_000_000_000

    def convert_sol_to_lamports(self, sol: float) -> int:
        """Convierte SOL a lamports"""
        return int(sol * 1_000_000_000)

    def format_balance(self, lamports: int) -> str:
        """Formatea un balance para mostrar"""
        sol = self.convert_lamports_to_sol(lamports)
        return f"{sol:.9f} SOL ({lamports:,} lamports)"

    def get_solana_price_usd(self) -> float:
        """Obtiene el precio actual de SOL en USD (requiere conexión a internet)"""
        try:
            import requests
            response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
            if response.status_code == 200:
                data = response.json()
                price = data['solana']['usd']
                print(f"💵 Precio SOL: ${price:.2f} USD")
                return price
            else:
                print("❌ No se pudo obtener el precio de SOL")
                return 0.0
        except Exception as e:
            print(f"❌ Error obteniendo precio SOL: {e}")
            return 0.0

    def calculate_sol_value_usd(self, sol_amount: float) -> float:
        """Calcula el valor en USD de una cantidad de SOL"""
        try:
            price_usd = self.get_solana_price_usd()
            if price_usd > 0:
                value_usd = sol_amount * price_usd
                print(f"💰 {sol_amount} SOL = ${value_usd:.2f} USD")
                return value_usd
            return 0.0
        except Exception as e:
            print(f"❌ Error calculando valor USD: {e}")
            return 0.0 