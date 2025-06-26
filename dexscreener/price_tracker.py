# -*- coding: utf-8 -*-
"""
DexScreener Price Tracker - Seguimiento de precios en tiempo real
Específicamente optimizado para tokens de Pump.fun
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from collections import defaultdict, deque

from solana_manager.wallet_manager import SolanaWalletManager
from jupiter.jupiter_dex import JupiterDEX


@dataclass
class TokenPrice:
    """Estructura para almacenar información de precio de token"""
    address: str
    symbol: str
    name: str
    price_usd: float
    price_sol: float
    market_cap: float
    liquidity_usd: float
    volume_24h: float
    price_change_24h: float
    dex: str
    pair_address: str
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'address': self.address,
            'symbol': self.symbol,
            'name': self.name,
            'price_usd': self.price_usd,
            'price_sol': self.price_sol,
            'market_cap': self.market_cap,
            'liquidity_usd': self.liquidity_usd,
            'volume_24h': self.volume_24h,
            'price_change_24h': self.price_change_24h,
            'dex': self.dex,
            'pair_address': self.pair_address,
            'timestamp': self.timestamp.isoformat()
        }


class DexScreenerPriceTracker:
    """
    Tracker de precios usando DexScreener API
    Integrado con SolanaWalletManager y Jupiter para precios SOL
    """
    
    def __init__(self, wallet_manager: SolanaWalletManager = None):
        """
        Inicializa el price tracker
        
        Args:
            wallet_manager: Opcional, para obtener precios SOL precisos
        """
        self.wallet_manager = wallet_manager
        self.jupiter = JupiterDEX(wallet_manager) if wallet_manager else None
        
        # APIs de DexScreener
        self.base_url = "https://api.dexscreener.com/latest/dex"
        self.search_url = f"{self.base_url}/search"
        self.tokens_url = f"{self.base_url}/tokens"
        self.pairs_url = f"{self.base_url}/pairs"
        
        # Cache de precios y configuración
        self.price_cache = {}
        self.price_history = defaultdict(lambda: deque(maxlen=1000))
        self.cache_duration = 30  # segundos
        
        # Callbacks para alertas
        self.price_alerts = {}  # {token_address: {'above': price, 'below': price, 'callback': func}}
        self.alert_callbacks = []
        
        print("📊 DexScreener Price Tracker inicializado")
        if wallet_manager:
            print(f"🌐 Integrado con wallet en {wallet_manager.network}")

    def get_token_price(self, token_address: str, force_refresh: bool = False) -> Optional[TokenPrice]:
        """
        Obtiene precio actual de un token específico con múltiples estrategias
        
        Args:
            token_address: Dirección del token
            force_refresh: Forzar actualización ignorando cache
            
        Returns:
            TokenPrice object con toda la información
        """
        try:
            # Verificar cache si no se fuerza refresh
            if not force_refresh and token_address in self.price_cache:
                cached_price, cached_time = self.price_cache[token_address]
                if (datetime.now() - cached_time).seconds < self.cache_duration:
                    return cached_price
            
            print(f"💰 Obteniendo precio para: {token_address[:8]}...")
            
            # Estrategia 1: Endpoint específico de token
            token_price = self._get_price_from_token_endpoint(token_address)
            if token_price:
                return token_price
            
            # Estrategia 2: Endpoint de pares por token
            token_price = self._get_price_from_pairs_endpoint(token_address)
            if token_price:
                return token_price
            
            print(f"❌ No se pudo obtener precio para {token_address[:8]}... en ninguna fuente")
            return None
            
        except Exception as e:
            print(f"❌ Error obteniendo precio: {e}")
            return None

    def get_token_price_by_symbol(self, symbol: str, prefer_pump: bool = True) -> Optional[TokenPrice]:
        """
        Busca token por símbolo y obtiene su precio
        
        Args:
            symbol: Símbolo del token (ej: "BONK")
            prefer_pump: Preferir tokens de Pump.fun
            
        Returns:
            TokenPrice del mejor match encontrado
        """
        try:
            print(f"🔍 Buscando precio para símbolo: {symbol}")
            
            response = requests.get(f"{self.search_url}?q={symbol}", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                if pairs:
                    # Filtrar por símbolo exacto
                    exact_matches = []
                    for pair in pairs:
                        base_token = pair.get('baseToken', {})
                        if base_token.get('symbol', '').upper() == symbol.upper():
                            exact_matches.append(pair)
                    
                    if exact_matches:
                        # Seleccionar el mejor match
                        if prefer_pump:
                            # Buscar específicamente pares de Pump.fun
                            pump_pairs = [p for p in exact_matches if p.get('dexId') == 'pump']
                            best_pair = pump_pairs[0] if pump_pairs else exact_matches[0]
                        else:
                            # Seleccionar por liquidez
                            best_pair = max(exact_matches, 
                                          key=lambda p: float(p.get('liquidity', {}).get('usd', 0)))
                        
                        token_address = best_pair.get('baseToken', {}).get('address', '')
                        token_price = self._parse_token_price(best_pair, token_address)
                        
                        print(f"✅ Token encontrado: {token_address[:8]}... | ${token_price.price_usd:.10f}")
                        return token_price
            
            print(f"❌ No se encontró token con símbolo: {symbol}")
            return None
            
        except Exception as e:
            print(f"❌ Error buscando token: {e}")
            return None

    def track_multiple_tokens(self, token_addresses: List[str], 
                            update_interval: int = 60) -> Dict[str, TokenPrice]:
        """
        Rastrea múltiples tokens simultáneamente
        
        Args:
            token_addresses: Lista de direcciones de tokens
            update_interval: Intervalo de actualización en segundos
            
        Returns:
            Dict con precios actuales de todos los tokens
        """
        print(f"📊 Iniciando tracking de {len(token_addresses)} tokens...")
        
        results = {}
        
        for i, token_address in enumerate(token_addresses, 1):
            print(f"🔄 Procesando token {i}/{len(token_addresses)}: {token_address[:8]}...")
            
            token_price = self.get_token_price(token_address)
            if token_price:
                results[token_address] = token_price
                print(f"   ✅ {token_price.symbol}: ${token_price.price_usd:.10f}")
            else:
                print(f"   ❌ No se pudo obtener precio")
            
            # Pequeña pausa para no sobrecargar la API
            if i < len(token_addresses):
                time.sleep(2)
        
        print(f"📊 Tracking completado: {len(results)}/{len(token_addresses)} tokens")
        return results

    def set_price_alert(self, token_address: str, above: float = None, 
                        below: float = None, callback: Callable = None):
        """
        Configura alertas de precio para un token
        
        Args:
            token_address: Dirección del token
            above: Precio por encima del cual alertar
            below: Precio por debajo del cual alertar
            callback: Función a llamar cuando se active la alerta
        """
        self.price_alerts[token_address] = {
            'above': above,
            'below': below,
            'callback': callback,
            'triggered_above': False,
            'triggered_below': False
        }
        
        print(f"🔔 Alerta configurada para {token_address[:8]}...")
        if above:
            print(f"   📈 Alertar si precio > ${above:.10f}")
        if below:
            print(f"   📉 Alertar si precio < ${below:.10f}")

    def get_price_history(self, token_address: str, hours: int = 24) -> List[Dict]:
        """
        Obtiene historial de precios de un token
        
        Args:
            token_address: Dirección del token
            hours: Horas de historial a obtener
            
        Returns:
            Lista de datos históricos de precio
        """
        if token_address not in self.price_history:
            return []
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        history = list(self.price_history[token_address])
        
        # Filtrar por tiempo
        filtered_history = [
            entry for entry in history 
            if entry['timestamp'] > cutoff_time
        ]
        
        return filtered_history

    def get_newest_tokens(self, hours: int = 24, limit: int = 50) -> List[TokenPrice]:
        """
        Obtiene tokens más nuevos creados en las últimas horas
        
        Args:
            hours: Horas hacia atrás para buscar
            limit: Número máximo de tokens a retornar
            
        Returns:
            Lista de tokens ordenados por fecha de creación (más nuevos primero)
        """
        try:
            print(f"🔍 Buscando tokens creados en las últimas {hours} horas...")
            
            # Usar endpoint de búsqueda para encontrar tokens recientes
            search_terms = ["pump", "new", "token", "meme"]
            all_new_tokens = []
            
            for term in search_terms:
                try:
                    response = requests.get(f"{self.search_url}?q={term}", timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        # Filtrar por edad del par
                        cutoff_time = datetime.now() - timedelta(hours=hours)
                        
                        for pair in pairs:
                            pair_created_at = pair.get('pairCreatedAt')
                            if pair_created_at:
                                try:
                                    # Convertir timestamp a datetime
                                    created_time = datetime.fromtimestamp(pair_created_at / 1000)
                                    
                                    # Solo tokens creados en el período especificado
                                    if created_time > cutoff_time:
                                        token_address = pair.get('baseToken', {}).get('address', '')
                                        if token_address:
                                            token_price = self._parse_token_price(pair, token_address)
                                            token_price.timestamp = created_time  # Usar tiempo de creación
                                            all_new_tokens.append(token_price)
                                            
                                except Exception as e:
                                    continue
                
                except Exception as e:
                    print(f"⚠️ Error buscando con término '{term}': {e}")
                    continue
            
            # Eliminar duplicados y ordenar por fecha de creación
            unique_tokens = {}
            for token in all_new_tokens:
                if token.address not in unique_tokens:
                    unique_tokens[token.address] = token
            
            new_tokens_list = list(unique_tokens.values())
            new_tokens_list.sort(key=lambda t: t.timestamp, reverse=True)
            
            result = new_tokens_list[:limit]
            print(f"✅ Encontrados {len(result)} tokens nuevos")
            
            # Mostrar los más nuevos
            if result:
                print(f"\n🆕 Top 5 tokens más nuevos:")
                for i, token in enumerate(result[:5], 1):
                    age_hours = (datetime.now() - token.timestamp).total_seconds() / 3600
                    print(f"   {i}. {token.symbol} - {age_hours:.1f}h - ${token.price_usd:.10f}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error obteniendo tokens nuevos: {e}")
            return []

    def get_trending_pump_tokens(self, limit: int = 20) -> List[TokenPrice]:
        """
        Obtiene tokens trending de Pump.fun
        
        Args:
            limit: Número máximo de tokens a retornar
            
        Returns:
            Lista de tokens trending ordenados por volumen/cambio de precio
        """
        try:
            print(f"🔥 Buscando tokens trending de Pump.fun...")
            
            # Buscar tokens con alto volumen en Pump.fun
            search_terms = ["pump", "meme", "new"]
            all_trending = []
            
            for term in search_terms:
                try:
                    response = requests.get(f"{self.search_url}?q={term}", timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        # Filtrar solo pares de Pump.fun con buen volumen
                        pump_pairs = [
                            pair for pair in pairs 
                            if (pair.get('dexId') == 'pump' and 
                                float(pair.get('volume', {}).get('h24', 0)) > 1000)
                        ]
                        
                        for pair in pump_pairs[:10]:  # Top 10 por término
                            token_address = pair.get('baseToken', {}).get('address', '')
                            if token_address:
                                token_price = self._parse_token_price(pair, token_address)
                                all_trending.append(token_price)
                
                except Exception as e:
                    print(f"⚠️ Error buscando con término '{term}': {e}")
                    continue
            
            # Eliminar duplicados y ordenar por volumen
            unique_tokens = {}
            for token in all_trending:
                if token.address not in unique_tokens:
                    unique_tokens[token.address] = token
            
            trending_list = list(unique_tokens.values())
            trending_list.sort(key=lambda t: t.volume_24h, reverse=True)
            
            result = trending_list[:limit]
            print(f"✅ Encontrados {len(result)} tokens trending")
            
            return result
            
        except Exception as e:
            print(f"❌ Error obteniendo tokens trending: {e}")
            return []

    def _select_best_pair(self, pairs: List[Dict]) -> Optional[Dict]:
        """Selecciona el mejor par de trading de una lista"""
        if not pairs:
            return None
        
        # Preferir Pump.fun
        pump_pairs = [p for p in pairs if p.get('dexId') == 'pump']
        if pump_pairs:
            return pump_pairs[0]
        
        # Si no hay Pump.fun, seleccionar por liquidez
        return max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0)))

    def _parse_token_price(self, pair_data: Dict, token_address: str) -> TokenPrice:
        """Convierte datos de DexScreener a TokenPrice object"""
        base_token = pair_data.get('baseToken', {})
        
        # Obtener precio SOL si tenemos Jupiter integrado
        price_usd = float(pair_data.get('priceUsd', 0))
        price_sol = 0.0
        
        if self.jupiter and price_usd > 0:
            try:
                sol_price = self.jupiter.get_token_price('SOL')
                if sol_price:
                    price_sol = price_usd / sol_price
            except:
                pass
        
        return TokenPrice(
            address=token_address,
            symbol=base_token.get('symbol', ''),
            name=base_token.get('name', ''),
            price_usd=price_usd,
            price_sol=price_sol,
            market_cap=float(pair_data.get('marketCap', 0)),
            liquidity_usd=float(pair_data.get('liquidity', {}).get('usd', 0)),
            volume_24h=float(pair_data.get('volume', {}).get('h24', 0)),
            price_change_24h=float(pair_data.get('priceChange', {}).get('h24', 0)),
            dex=pair_data.get('dexId', ''),
            pair_address=pair_data.get('pairAddress', ''),
            timestamp=datetime.now()
        )

    def _check_price_alerts(self, token_price: TokenPrice):
        """Verifica y dispara alertas de precio"""
        token_address = token_price.address
        
        if token_address not in self.price_alerts:
            return
        
        alert_config = self.price_alerts[token_address]
        price = token_price.price_usd
        
        # Verificar alerta superior
        if (alert_config['above'] and 
            price >= alert_config['above'] and 
            not alert_config['triggered_above']):
            
            alert_config['triggered_above'] = True
            self._trigger_alert(token_price, 'above', alert_config['above'])
            
            if alert_config['callback']:
                alert_config['callback'](token_price, 'above')
        
        # Verificar alerta inferior
        if (alert_config['below'] and 
            price <= alert_config['below'] and 
            not alert_config['triggered_below']):
            
            alert_config['triggered_below'] = True
            self._trigger_alert(token_price, 'below', alert_config['below'])
            
            if alert_config['callback']:
                alert_config['callback'](token_price, 'below')

    def _get_price_from_token_endpoint(self, token_address: str) -> Optional[TokenPrice]:
        """Estrategia 1: Usar endpoint específico de tokens"""
        try:
            response = requests.get(f"{self.tokens_url}/{token_address}", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                if pairs:
                    # Validar que el token en el par coincida con el solicitado
                    valid_pairs = []
                    for pair in pairs:
                        base_token = pair.get('baseToken', {})
                        base_address = base_token.get('address', '')
                        
                        # Verificar que la dirección coincida exactamente
                        if base_address.lower() == token_address.lower():
                            valid_pairs.append(pair)
                    
                    if valid_pairs:
                        best_pair = self._select_best_pair(valid_pairs)
                        if best_pair:
                            token_price = self._parse_token_price(best_pair, token_address)
                            
                            # Validación adicional para stablecoins
                            if self._is_stablecoin_address(token_address):
                                if token_price.price_usd > 2.0:  # USDC no debería ser > $2
                                    print(f"⚠️ Precio sospechoso para stablecoin: ${token_price.price_usd:.6f}")
                                    return None
                            
                            self._cache_and_track_price(token_price)
                            print(f"✅ Precio obtenido desde DexScreener tokens: ${token_price.price_usd:.10f} USD")
                            return token_price
                    else:
                        print(f"⚠️ No se encontraron pares válidos para {token_address[:8]}...")
            
            return None
            
        except Exception as e:
            print(f"⚠️ Error en endpoint tokens: {e}")
            return None

    def _get_price_from_pairs_endpoint(self, token_address: str) -> Optional[TokenPrice]:
        """Estrategia 2: Usar endpoint de pares por token (mejor para tokens nuevos)"""
        try:
            # Usar el endpoint alternativo para pares por token
            url = f"https://api.dexscreener.com/token-pairs/v1/solana/{token_address}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                pairs = response.json()
                
                if pairs and len(pairs) > 0:
                    # Filtrar solo pares de Pump.fun o con liquidez
                    pump_pairs = [p for p in pairs if p.get('dexId') == 'pump']
                    valid_pairs = pump_pairs if pump_pairs else pairs
                    
                    if valid_pairs:
                        best_pair = self._select_best_pair(valid_pairs)
                        if best_pair:
                            token_price = self._parse_token_price(best_pair, token_address)
                            self._cache_and_track_price(token_price)
                            print(f"✅ Precio obtenido desde DexScreener pairs: ${token_price.price_usd:.10f} USD")
                            return token_price
            
            return None
            
        except Exception as e:
            print(f"⚠️ Error en endpoint pairs: {e}")
            return None

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
                return 140.0  # Precio de fallback
                
        except Exception:
            return 140.0  # Precio de emergencia

    def _cache_and_track_price(self, token_price: TokenPrice):
        """Guarda precio en cache y historial"""
        # Guardar en cache
        self.price_cache[token_price.address] = (token_price, datetime.now())
        
        # Agregar al historial
        self.price_history[token_price.address].append({
            'price_usd': token_price.price_usd,
            'timestamp': token_price.timestamp
        })
        
        # Verificar alertas
        self._check_price_alerts(token_price)

    def _trigger_alert(self, token_price: TokenPrice, direction: str, threshold: float):
        """Dispara una alerta de precio"""
        emoji = "📈" if direction == "above" else "📉"
        print(f"\n🚨🚨🚨 ALERTA DE PRECIO {emoji}")
        print(f"🪙 Token: {token_price.symbol} ({token_price.address[:8]}...)")
        print(f"💰 Precio actual: ${token_price.price_usd:.10f}")
        print(f"🎯 Umbral {direction}: ${threshold:.10f}")
        print(f"⏰ Tiempo: {token_price.timestamp.strftime('%H:%M:%S')}")
        print("🚨🚨🚨\n")

    def _is_stablecoin_address(self, token_address: str) -> bool:
        """Verifica si una dirección corresponde a un stablecoin conocido"""
        stablecoin_addresses = {
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',   # USDT
            '4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU',   # USDC (SPL)
            'Dn4noZ5jgGfkntzcQSUZ8czkreiZ1ForXYoV2H8Dm7S1',   # UXD
            '5RpUwQ8wtdPCZHhu6MERp2RGrpobsbZ6MH5dDHkUjs2'    # BUSD
        }
        return token_address in stablecoin_addresses

    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado del price tracker"""
        return {
            'tokens_cached': len(self.price_cache),
            'tokens_with_history': len(self.price_history),
            'active_alerts': len(self.price_alerts),
            'jupiter_integrated': self.jupiter is not None,
            'wallet_connected': self.wallet_manager is not None,
            'cache_duration': self.cache_duration
        } 