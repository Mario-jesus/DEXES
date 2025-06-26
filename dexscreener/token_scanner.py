# -*- coding: utf-8 -*-
"""
DexScreener Token Scanner - Detecta nuevos tokens y oportunidades
Específicamente orientado a Pump.fun con análisis de riesgo
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

from solana_manager.wallet_manager import SolanaWalletManager
from .price_tracker import DexScreenerPriceTracker, TokenPrice


@dataclass
class TokenOpportunity:
    """Estructura para oportunidades de trading detectadas"""
    token_price: TokenPrice
    opportunity_type: str  # 'new_token', 'price_surge', 'volume_spike', 'low_market_cap'
    score: float  # 0-100, mayor es mejor
    risk_level: str  # 'low', 'medium', 'high'
    analysis: Dict[str, Any]
    detected_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'token': self.token_price.to_dict(),
            'opportunity_type': self.opportunity_type,
            'score': self.score,
            'risk_level': self.risk_level,
            'analysis': self.analysis,
            'detected_at': self.detected_at.isoformat()
        }


class DexScreenerTokenScanner:
    """
    Scanner de tokens usando DexScreener para detectar oportunidades
    Integrado con el price tracker y análisis de riesgo
    """
    
    def __init__(self, wallet_manager: SolanaWalletManager = None):
        """
        Inicializa el token scanner
        
        Args:
            wallet_manager: Opcional, para integración con otros módulos
        """
        self.wallet_manager = wallet_manager
        self.price_tracker = DexScreenerPriceTracker(wallet_manager)
        
        # Configuración de scanning
        self.scan_interval = 60  # segundos
        self.min_liquidity = 5000  # USD mínimo de liquidez
        self.min_volume_24h = 1000  # USD mínimo de volumen 24h
        self.max_market_cap = 1000000  # USD máximo market cap para "gems"
        
        # Tracking de tokens conocidos
        self.known_tokens = set()
        self.opportunity_history = []
        self.scan_stats = {
            'total_scans': 0,
            'tokens_found': 0,
            'opportunities_detected': 0,
            'last_scan': None
        }
        
        print("🔍 DexScreener Token Scanner inicializado")
        print(f"🎯 Configuración: Liquidez min ${self.min_liquidity:,}, Volumen min ${self.min_volume_24h:,}")

    def scan_new_pump_tokens(self, limit: int = 50) -> List[TokenOpportunity]:
        """
        Escanea nuevos tokens de Pump.fun buscando oportunidades
        
        Args:
            limit: Número máximo de tokens a analizar
            
        Returns:
            Lista de oportunidades detectadas
        """
        try:
            print(f"🔍 Escaneando nuevos tokens de Pump.fun...")
            self.scan_stats['total_scans'] += 1
            self.scan_stats['last_scan'] = datetime.now()
            
            opportunities = []
            
            # Obtener tokens trending de Pump.fun
            trending_tokens = self.price_tracker.get_trending_pump_tokens(limit)
            
            print(f"📊 Analizando {len(trending_tokens)} tokens trending...")
            
            for i, token_price in enumerate(trending_tokens, 1):
                print(f"🔄 Analizando token {i}/{len(trending_tokens)}: {token_price.symbol}")
                
                # Verificar si es nuevo
                is_new = token_price.address not in self.known_tokens
                if is_new:
                    self.known_tokens.add(token_price.address)
                    self.scan_stats['tokens_found'] += 1
                
                # Analizar oportunidades
                token_opportunities = self._analyze_token_opportunities(token_price, is_new)
                opportunities.extend(token_opportunities)
                
                # Pequeña pausa para no sobrecargar
                time.sleep(1)
            
            # Ordenar por score
            opportunities.sort(key=lambda o: o.score, reverse=True)
            
            # Actualizar estadísticas
            self.scan_stats['opportunities_detected'] += len(opportunities)
            self.opportunity_history.extend(opportunities)
            
            # Mantener solo últimas 1000 oportunidades
            if len(self.opportunity_history) > 1000:
                self.opportunity_history = self.opportunity_history[-1000:]
            
            print(f"✅ Scan completado: {len(opportunities)} oportunidades detectadas")
            
            return opportunities
            
        except Exception as e:
            print(f"❌ Error en scan de tokens: {e}")
            return []

    def scan_price_movements(self, token_addresses: List[str], 
                           price_change_threshold: float = 20.0) -> List[TokenOpportunity]:
        """
        Escanea movimientos de precio significativos
        
        Args:
            token_addresses: Lista de tokens a monitorear
            price_change_threshold: % mínimo de cambio para considerar oportunidad
            
        Returns:
            Lista de oportunidades por movimiento de precio
        """
        try:
            print(f"📈 Escaneando movimientos de precio en {len(token_addresses)} tokens...")
            
            opportunities = []
            
            for token_address in token_addresses:
                token_price = self.price_tracker.get_token_price(token_address)
                
                if token_price and abs(token_price.price_change_24h) >= price_change_threshold:
                    opportunity_type = 'price_surge' if token_price.price_change_24h > 0 else 'price_drop'
                    
                    # Calcular score basado en el cambio de precio
                    score = min(abs(token_price.price_change_24h) * 2, 100)
                    
                    # Determinar riesgo
                    risk_level = self._calculate_risk_level(token_price)
                    
                    analysis = {
                        'price_change_24h': token_price.price_change_24h,
                        'volume_24h': token_price.volume_24h,
                        'liquidity': token_price.liquidity_usd,
                        'market_cap': token_price.market_cap
                    }
                    
                    opportunity = TokenOpportunity(
                        token_price=token_price,
                        opportunity_type=opportunity_type,
                        score=score,
                        risk_level=risk_level,
                        analysis=analysis,
                        detected_at=datetime.now()
                    )
                    
                    opportunities.append(opportunity)
                    print(f"🎯 Oportunidad: {token_price.symbol} {token_price.price_change_24h:+.1f}%")
            
            return opportunities
            
        except Exception as e:
            print(f"❌ Error escaneando movimientos: {e}")
            return []

    def scan_volume_spikes(self, volume_multiplier: float = 5.0) -> List[TokenOpportunity]:
        """
        Escanea tokens con picos de volumen inusuales
        
        Args:
            volume_multiplier: Multiplicador de volumen para considerar "spike"
            
        Returns:
            Lista de oportunidades por volumen
        """
        try:
            print(f"📊 Escaneando picos de volumen...")
            
            # Obtener tokens con alto volumen
            trending_tokens = self.price_tracker.get_trending_pump_tokens(100)
            
            opportunities = []
            
            for token_price in trending_tokens:
                # Verificar si el volumen es inusualmente alto
                # (esto requeriría historial, por ahora usamos volumen absoluto)
                if token_price.volume_24h > self.min_volume_24h * volume_multiplier:
                    
                    score = min((token_price.volume_24h / self.min_volume_24h) * 10, 100)
                    risk_level = self._calculate_risk_level(token_price)
                    
                    analysis = {
                        'volume_24h': token_price.volume_24h,
                        'volume_multiplier': token_price.volume_24h / self.min_volume_24h,
                        'liquidity': token_price.liquidity_usd,
                        'market_cap': token_price.market_cap
                    }
                    
                    opportunity = TokenOpportunity(
                        token_price=token_price,
                        opportunity_type='volume_spike',
                        score=score,
                        risk_level=risk_level,
                        analysis=analysis,
                        detected_at=datetime.now()
                    )
                    
                    opportunities.append(opportunity)
                    print(f"🔥 Volumen spike: {token_price.symbol} ${token_price.volume_24h:,.0f}")
            
            return opportunities
            
        except Exception as e:
            print(f"❌ Error escaneando volumen: {e}")
            return []

    def scan_low_market_cap_gems(self, max_market_cap: float = None) -> List[TokenOpportunity]:
        """
        Escanea tokens con market cap bajo pero buenas métricas (posibles "gems")
        
        Args:
            max_market_cap: Market cap máximo a considerar
            
        Returns:
            Lista de posibles "gems" detectadas
        """
        try:
            max_cap = max_market_cap or self.max_market_cap
            print(f"💎 Escaneando gems con market cap < ${max_cap:,}...")
            
            # Buscar tokens con diferentes términos
            search_terms = ["meme", "new", "pump", "coin", "token"]
            all_tokens = []
            
            for term in search_terms:
                try:
                    response = requests.get(f"{self.price_tracker.search_url}?q={term}", timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        # Filtrar pares de Pump.fun con market cap bajo
                        pump_pairs = [
                            pair for pair in pairs 
                            if (pair.get('dexId') == 'pump' and 
                                float(pair.get('marketCap', 0)) < max_cap and
                                float(pair.get('marketCap', 0)) > 1000 and  # Mínimo para evitar scams
                                float(pair.get('liquidity', {}).get('usd', 0)) > self.min_liquidity)
                        ]
                        
                        for pair in pump_pairs[:20]:  # Top 20 por término
                            token_address = pair.get('baseToken', {}).get('address', '')
                            if token_address:
                                token_price = self.price_tracker._parse_token_price(pair, token_address)
                                all_tokens.append(token_price)
                
                except Exception as e:
                    print(f"⚠️ Error buscando con término '{term}': {e}")
                    continue
            
            # Eliminar duplicados
            unique_tokens = {}
            for token in all_tokens:
                if token.address not in unique_tokens:
                    unique_tokens[token.address] = token
            
            opportunities = []
            
            for token_price in unique_tokens.values():
                # Calcular score para gems
                score = self._calculate_gem_score(token_price)
                
                if score > 30:  # Solo considerar tokens con score decente
                    risk_level = self._calculate_risk_level(token_price)
                    
                    analysis = {
                        'market_cap': token_price.market_cap,
                        'liquidity_ratio': token_price.liquidity_usd / max(token_price.market_cap, 1),
                        'volume_ratio': token_price.volume_24h / max(token_price.market_cap, 1),
                        'gem_score': score
                    }
                    
                    opportunity = TokenOpportunity(
                        token_price=token_price,
                        opportunity_type='low_market_cap',
                        score=score,
                        risk_level=risk_level,
                        analysis=analysis,
                        detected_at=datetime.now()
                    )
                    
                    opportunities.append(opportunity)
                    print(f"💎 Gem detectada: {token_price.symbol} MC: ${token_price.market_cap:,.0f}")
            
            # Ordenar por score
            opportunities.sort(key=lambda o: o.score, reverse=True)
            
            return opportunities[:20]  # Top 20 gems
            
        except Exception as e:
            print(f"❌ Error escaneando gems: {e}")
            return []

    def get_scanning_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del scanning
        
        Returns:
            Estadísticas detalladas del scanner
        """
        stats = self.scan_stats.copy()
        
        # Mapear nombres de campos para compatibilidad con notebook
        mapped_stats = {
            'tokens_scanned': stats.get('total_scans', 0),
            'opportunities_found': stats.get('opportunities_detected', 0),
            'unique_tokens': stats.get('tokens_found', 0),
            'last_scan': stats.get('last_scan').isoformat() if stats.get('last_scan') else None,
            'total_scans': stats.get('total_scans', 0),
            'tokens_found': stats.get('tokens_found', 0),
            'opportunities_detected': stats.get('opportunities_detected', 0)
        }
        
        # Agregar estadísticas de oportunidades
        if self.opportunity_history:
            opportunity_types = defaultdict(int)
            for opp in self.opportunity_history:
                opportunity_types[opp.opportunity_type] += 1
            
            mapped_stats['opportunity_types'] = dict(opportunity_types)
            mapped_stats['total_opportunities_detected'] = len(self.opportunity_history)
            
            # Última oportunidad detectada
            if self.opportunity_history:
                last_opp = max(self.opportunity_history, key=lambda o: o.detected_at)
                mapped_stats['last_opportunity'] = last_opp.detected_at.isoformat()
        else:
            mapped_stats['opportunity_types'] = {}
            mapped_stats['total_opportunities_detected'] = 0
            mapped_stats['last_opportunity'] = None
        
        return mapped_stats

    def get_opportunity_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Obtiene resumen de oportunidades detectadas
        
        Args:
            hours: Horas hacia atrás para el resumen
            
        Returns:
            Resumen de oportunidades por tipo y riesgo
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_opportunities = [
            opp for opp in self.opportunity_history 
            if opp.detected_at > cutoff_time
        ]
        
        summary = {
            'total_opportunities': len(recent_opportunities),
            'by_type': defaultdict(int),
            'by_risk': defaultdict(int),
            'avg_score': 0,
            'best_opportunity': None,
            'scan_stats': self.scan_stats.copy()
        }
        
        if recent_opportunities:
            # Agrupar por tipo y riesgo
            for opp in recent_opportunities:
                summary['by_type'][opp.opportunity_type] += 1
                summary['by_risk'][opp.risk_level] += 1
            
            # Calcular promedio de score
            summary['avg_score'] = sum(opp.score for opp in recent_opportunities) / len(recent_opportunities)
            
            # Mejor oportunidad
            best_opp = max(recent_opportunities, key=lambda o: o.score)
            summary['best_opportunity'] = {
                'token': best_opp.token_price.symbol,
                'type': best_opp.opportunity_type,
                'score': best_opp.score,
                'risk': best_opp.risk_level
            }
        
        return dict(summary)

    def _analyze_token_opportunities(self, token_price: TokenPrice, is_new: bool) -> List[TokenOpportunity]:
        """Analiza un token específico buscando oportunidades"""
        opportunities = []
        
        # Oportunidad: Token nuevo
        if is_new:
            score = self._calculate_new_token_score(token_price)
            risk_level = self._calculate_risk_level(token_price)
            
            analysis = {
                'age': 'new',
                'initial_metrics': {
                    'market_cap': token_price.market_cap,
                    'liquidity': token_price.liquidity_usd,
                    'volume_24h': token_price.volume_24h
                }
            }
            
            opportunity = TokenOpportunity(
                token_price=token_price,
                opportunity_type='new_token',
                score=score,
                risk_level=risk_level,
                analysis=analysis,
                detected_at=datetime.now()
            )
            
            opportunities.append(opportunity)
        
        return opportunities

    def _calculate_new_token_score(self, token_price: TokenPrice) -> float:
        """Calcula score para tokens nuevos"""
        score = 0
        
        # Liquidez (0-30 puntos)
        if token_price.liquidity_usd > 50000:
            score += 30
        elif token_price.liquidity_usd > 20000:
            score += 20
        elif token_price.liquidity_usd > 10000:
            score += 10
        
        # Volumen (0-25 puntos)
        if token_price.volume_24h > 100000:
            score += 25
        elif token_price.volume_24h > 50000:
            score += 20
        elif token_price.volume_24h > 10000:
            score += 15
        elif token_price.volume_24h > 5000:
            score += 10
        
        # Market cap razonable (0-20 puntos)
        if 10000 <= token_price.market_cap <= 500000:
            score += 20
        elif 5000 <= token_price.market_cap <= 1000000:
            score += 15
        elif token_price.market_cap > 0:
            score += 5
        
        # DEX (0-15 puntos)
        if token_price.dex == 'pump':
            score += 15
        
        # Ratio volumen/market cap (0-10 puntos)
        if token_price.market_cap > 0:
            vol_mc_ratio = token_price.volume_24h / token_price.market_cap
            if vol_mc_ratio > 0.5:
                score += 10
            elif vol_mc_ratio > 0.2:
                score += 7
            elif vol_mc_ratio > 0.1:
                score += 5
        
        return min(score, 100)

    def _calculate_gem_score(self, token_price: TokenPrice) -> float:
        """Calcula score para posibles gems (market cap bajo)"""
        score = 0
        
        # Market cap bajo pero no demasiado (0-25 puntos)
        if 5000 <= token_price.market_cap <= 100000:
            score += 25
        elif 1000 <= token_price.market_cap <= 500000:
            score += 20
        elif token_price.market_cap <= 1000000:
            score += 15
        
        # Liquidez decente (0-20 puntos)
        if token_price.liquidity_usd > 20000:
            score += 20
        elif token_price.liquidity_usd > 10000:
            score += 15
        elif token_price.liquidity_usd > 5000:
            score += 10
        
        # Volumen activo (0-20 puntos)
        if token_price.volume_24h > 50000:
            score += 20
        elif token_price.volume_24h > 20000:
            score += 15
        elif token_price.volume_24h > 10000:
            score += 10
        elif token_price.volume_24h > 5000:
            score += 5
        
        # Ratio liquidez/market cap (0-15 puntos)
        if token_price.market_cap > 0:
            liq_mc_ratio = token_price.liquidity_usd / token_price.market_cap
            if liq_mc_ratio > 0.3:
                score += 15
            elif liq_mc_ratio > 0.2:
                score += 12
            elif liq_mc_ratio > 0.1:
                score += 8
            elif liq_mc_ratio > 0.05:
                score += 5
        
        # Cambio de precio positivo (0-10 puntos)
        if token_price.price_change_24h > 20:
            score += 10
        elif token_price.price_change_24h > 10:
            score += 7
        elif token_price.price_change_24h > 0:
            score += 5
        
        # DEX preferido (0-10 puntos)
        if token_price.dex == 'pump':
            score += 10
        
        return min(score, 100)

    def _calculate_risk_level(self, token_price: TokenPrice) -> str:
        """Calcula nivel de riesgo de un token"""
        risk_score = 0
        
        # Market cap muy bajo = más riesgo
        if token_price.market_cap < 5000:
            risk_score += 30
        elif token_price.market_cap < 50000:
            risk_score += 20
        elif token_price.market_cap < 500000:
            risk_score += 10
        
        # Liquidez baja = más riesgo
        if token_price.liquidity_usd < 5000:
            risk_score += 25
        elif token_price.liquidity_usd < 15000:
            risk_score += 15
        elif token_price.liquidity_usd < 50000:
            risk_score += 10
        
        # Volumen bajo = más riesgo
        if token_price.volume_24h < 1000:
            risk_score += 20
        elif token_price.volume_24h < 5000:
            risk_score += 15
        elif token_price.volume_24h < 20000:
            risk_score += 10
        
        # Determinar nivel
        if risk_score >= 60:
            return 'high'
        elif risk_score >= 30:
            return 'medium'
        else:
            return 'low' 