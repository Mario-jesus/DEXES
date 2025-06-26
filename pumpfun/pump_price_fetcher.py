#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pump.fun Price Fetcher - Obtiene precios directamente de la bonding curve
Basado en el método oficial de Pump.fun para calcular precios
"""

import struct
import requests
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from solana_manager import SolanaWalletManager
from solders.pubkey import Pubkey as PublicKey


@dataclass
class PumpCurveState:
    """Estado de la bonding curve de Pump.fun"""
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'virtual_token_reserves': self.virtual_token_reserves,
            'virtual_sol_reserves': self.virtual_sol_reserves,
            'real_token_reserves': self.real_token_reserves,
            'real_sol_reserves': self.real_sol_reserves,
            'token_total_supply': self.token_total_supply,
            'complete': self.complete
        }


@dataclass
class PumpTokenPrice:
    """Precio de token de Pump.fun"""
    token_address: str
    price_sol: float
    price_usd: float
    market_cap_usd: float
    bonding_progress: float
    curve_state: PumpCurveState
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'token_address': self.token_address,
            'price_sol': self.price_sol,
            'price_usd': self.price_usd,
            'market_cap_usd': self.market_cap_usd,
            'bonding_progress': self.bonding_progress,
            'curve_state': self.curve_state.to_dict(),
            'timestamp': self.timestamp.isoformat()
        }


class PumpFunPriceFetcher:
    """
    Fetcher de precios para tokens de Pump.fun
    Accede directamente a la bonding curve usando RPC de Solana
    """
    
    # Constantes de Pump.fun
    PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    PUMP_CURVE_SEED = b"bonding-curve"
    PUMP_CURVE_TOKEN_DECIMALS = 6
    LAMPORTS_PER_SOL = 1_000_000_000
    
    # Signature de la bonding curve (primeros 8 bytes de sha256("account:BondingCurve"))
    PUMP_CURVE_STATE_SIGNATURE = bytes([0x17, 0xb7, 0xf8, 0x37, 0x60, 0xd8, 0xac, 0x60])
    
    # Offsets para deserializar los datos de la curve
    CURVE_STATE_OFFSETS = {
        'VIRTUAL_TOKEN_RESERVES': 0x08,
        'VIRTUAL_SOL_RESERVES': 0x10,
        'REAL_TOKEN_RESERVES': 0x18,
        'REAL_SOL_RESERVES': 0x20,
        'TOKEN_TOTAL_SUPPLY': 0x28,
        'COMPLETE': 0x30,
    }
    
    # Reservas iniciales para calcular progreso de bonding curve
    INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        """
        Inicializa el fetcher de precios de Pump.fun
        
        Args:
            wallet_manager: Instancia de SolanaWalletManager para conexión RPC
        """
        self.wallet_manager = wallet_manager
        self.rpc_client = wallet_manager.client
        
        print("🎯 Pump.fun Price Fetcher inicializado")
        print(f"🌐 Conectado a {wallet_manager.network}")

    def find_pump_curve_address(self, token_mint: str) -> str:
        """
        Encuentra la dirección de la bonding curve para un token
        
        Args:
            token_mint: Dirección del token mint
            
        Returns:
            Dirección de la bonding curve
        """
        try:
            token_pubkey = PublicKey.from_string(token_mint)
            program_pubkey = PublicKey.from_string(self.PUMP_PROGRAM_ID)
            
            # Encontrar PDA (Program Derived Address)
            curve_address, _ = PublicKey.find_program_address(
                [self.PUMP_CURVE_SEED, bytes(token_pubkey)],
                program_pubkey
            )
            
            return str(curve_address)
            
        except Exception as e:
            print(f"❌ Error encontrando curve address: {e}")
            return None

    def get_pump_curve_state(self, curve_address: str) -> Optional[PumpCurveState]:
        """
        Obtiene el estado de la bonding curve desde la blockchain
        
        Args:
            curve_address: Dirección de la bonding curve
            
        Returns:
            Estado de la curve o None si hay error
        """
        try:
            curve_pubkey = PublicKey.from_string(curve_address)
            
            # Obtener datos de la cuenta
            response = self.rpc_client.get_account_info(curve_pubkey)
            
            if not response.value or not response.value.data:
                print(f"❌ No se encontraron datos de la curve")
                return None
            
            # Deserializar datos
            data = response.value.data
            
            # Verificar signature
            if len(data) < len(self.PUMP_CURVE_STATE_SIGNATURE) + 0x31:
                print(f"❌ Datos de curve incompletos")
                return None
            
            signature = data[:len(self.PUMP_CURVE_STATE_SIGNATURE)]
            if signature != self.PUMP_CURVE_STATE_SIGNATURE:
                print(f"❌ Signature de curve inválida")
                return None
            
            # Extraer datos usando offsets
            def read_u64_le(offset: int) -> int:
                return struct.unpack('<Q', data[offset:offset + 8])[0]
            
            def read_bool(offset: int) -> bool:
                return data[offset] != 0
            
            curve_state = PumpCurveState(
                virtual_token_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_TOKEN_RESERVES']),
                virtual_sol_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_SOL_RESERVES']),
                real_token_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['REAL_TOKEN_RESERVES']),
                real_sol_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['REAL_SOL_RESERVES']),
                token_total_supply=read_u64_le(self.CURVE_STATE_OFFSETS['TOKEN_TOTAL_SUPPLY']),
                complete=read_bool(self.CURVE_STATE_OFFSETS['COMPLETE'])
            )
            
            return curve_state
            
        except Exception as e:
            print(f"❌ Error obteniendo curve state: {e}")
            return None

    def calculate_pump_curve_price(self, curve_state: PumpCurveState) -> float:
        """
        Calcula el precio del token basado en el estado de la bonding curve
        Usa la fórmula oficial de Pump.fun
        
        Args:
            curve_state: Estado de la bonding curve
            
        Returns:
            Precio del token en SOL
        """
        try:
            if (curve_state.virtual_token_reserves <= 0 or 
                curve_state.virtual_sol_reserves <= 0):
                print(f"❌ Reservas inválidas en la curve")
                return 0.0
            
            # Fórmula oficial de Pump.fun:
            # price = (virtual_sol_reserves / LAMPORTS_PER_SOL) / (virtual_token_reserves / 10^decimals)
            
            sol_reserves = curve_state.virtual_sol_reserves / self.LAMPORTS_PER_SOL
            token_reserves = curve_state.virtual_token_reserves / (10 ** self.PUMP_CURVE_TOKEN_DECIMALS)
            
            price_sol = sol_reserves / token_reserves
            
            return price_sol
            
        except Exception as e:
            print(f"❌ Error calculando precio: {e}")
            return 0.0

    def calculate_bonding_progress(self, curve_state: PumpCurveState) -> float:
        """
        Calcula el progreso de la bonding curve (0-100%)
        
        Args:
            curve_state: Estado de la bonding curve
            
        Returns:
            Progreso en porcentaje (0.0 - 100.0)
        """
        try:
            if curve_state.real_token_reserves >= self.INITIAL_REAL_TOKEN_RESERVES:
                return 0.0
            
            progress = (1 - (curve_state.real_token_reserves / self.INITIAL_REAL_TOKEN_RESERVES)) * 100
            
            return max(0.0, min(100.0, progress))
            
        except Exception as e:
            print(f"❌ Error calculando progreso: {e}")
            return 0.0

    def get_sol_price_usd(self) -> float:
        """
        Obtiene el precio de SOL en USD usando Jupiter
        
        Returns:
            Precio de SOL en USD
        """
        try:
            url = "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                price = float(data['data']['So11111111111111111111111111111111111111112']['price'])
                return price
            else:
                return 140.0  # Precio de fallback
                
        except Exception:
            return 140.0  # Precio de emergencia

    def get_token_price(self, token_address: str) -> Optional[PumpTokenPrice]:
        """
        Obtiene el precio completo de un token de Pump.fun
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Información completa del precio o None si hay error
        """
        try:
            print(f"🎯 Obteniendo precio de Pump.fun para: {token_address[:8]}...")
            
            # 1. Encontrar dirección de la bonding curve
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                print(f"❌ No se pudo encontrar bonding curve")
                return None
            
            print(f"📍 Curve address: {curve_address[:8]}...")
            
            # 2. Obtener estado de la curve
            curve_state = self.get_pump_curve_state(curve_address)
            if not curve_state:
                print(f"❌ No se pudo obtener estado de la curve")
                return None
            
            # 3. Calcular precio en SOL
            price_sol = self.calculate_pump_curve_price(curve_state)
            if price_sol <= 0:
                print(f"❌ Precio calculado inválido")
                return None
            
            # 4. Obtener precio de SOL en USD
            sol_price_usd = self.get_sol_price_usd()
            price_usd = price_sol * sol_price_usd
            
            # 5. Calcular market cap (asumiendo 1B tokens)
            market_cap_usd = price_usd * 1_000_000_000
            
            # 6. Calcular progreso de bonding curve
            bonding_progress = self.calculate_bonding_progress(curve_state)
            
            # 7. Crear resultado
            token_price = PumpTokenPrice(
                token_address=token_address,
                price_sol=price_sol,
                price_usd=price_usd,
                market_cap_usd=market_cap_usd,
                bonding_progress=bonding_progress,
                curve_state=curve_state,
                timestamp=datetime.now()
            )
            
            print(f"✅ Precio obtenido desde Pump.fun!")
            print(f"   💰 Precio: {price_sol:.12f} SOL (${price_usd:.12f})")
            print(f"   📊 Market Cap: ${market_cap_usd:,.2f}")
            print(f"   📈 Progreso Bonding: {bonding_progress:.2f}%")
            
            return token_price
            
        except Exception as e:
            print(f"❌ Error obteniendo precio de Pump.fun: {e}")
            return None

    def is_token_on_pump_curve(self, token_address: str) -> bool:
        """
        Verifica si un token está en una bonding curve de Pump.fun
        
        Args:
            token_address: Dirección del token
            
        Returns:
            True si está en bonding curve, False si no
        """
        try:
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                return False
            
            curve_state = self.get_pump_curve_state(curve_address)
            return curve_state is not None
            
        except Exception:
            return False

    def get_curve_info(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene información detallada de la bonding curve
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Información de la curve o None
        """
        try:
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                return None
            
            curve_state = self.get_pump_curve_state(curve_address)
            if not curve_state:
                return None
            
            price_sol = self.calculate_pump_curve_price(curve_state)
            bonding_progress = self.calculate_bonding_progress(curve_state)
            
            return {
                'curve_address': curve_address,
                'price_sol': price_sol,
                'bonding_progress': bonding_progress,
                'curve_complete': curve_state.complete,
                'virtual_reserves': {
                    'token': curve_state.virtual_token_reserves,
                    'sol': curve_state.virtual_sol_reserves
                },
                'real_reserves': {
                    'token': curve_state.real_token_reserves,
                    'sol': curve_state.real_sol_reserves
                },
                'total_supply': curve_state.token_total_supply
            }
            
        except Exception as e:
            print(f"❌ Error obteniendo info de curve: {e}")
            return None 