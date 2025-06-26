# -*- coding: utf-8 -*-
"""
DexScreener Pump Analyzer - Análisis específico para tokens de Pump.fun
Incluye métricas de seguridad, análisis de riesgo y recomendaciones
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from solana_manager.wallet_manager import SolanaWalletManager
from .price_tracker import DexScreenerPriceTracker, TokenPrice


@dataclass
class PumpAnalysis:
    """Análisis completo de un token de Pump.fun"""
    token_price: TokenPrice
    safety_score: float  # 0-100, mayor es más seguro
    potential_score: float  # 0-100, mayor es más potencial
    recommendation: str  # 'strong_buy', 'buy', 'hold', 'sell', 'avoid'
    risk_factors: List[str]
    positive_factors: List[str]
    technical_analysis: Dict[str, Any]
    fundamental_analysis: Dict[str, Any]
    trading_suggestion: Dict[str, Any]
    analyzed_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'token': self.token_price.to_dict(),
            'safety_score': self.safety_score,
            'potential_score': self.potential_score,
            'recommendation': self.recommendation,
            'risk_factors': self.risk_factors,
            'positive_factors': self.positive_factors,
            'technical_analysis': self.technical_analysis,
            'fundamental_analysis': self.fundamental_analysis,
            'trading_suggestion': self.trading_suggestion,
            'analyzed_at': self.analyzed_at.isoformat()
        }


class DexScreenerPumpAnalyzer:
    """
    Analizador especializado para tokens de Pump.fun
    Proporciona análisis técnico, fundamental y recomendaciones de trading
    """
    
    def __init__(self, wallet_manager: SolanaWalletManager = None):
        """
        Inicializa el analizador de Pump.fun
        
        Args:
            wallet_manager: Opcional, para integración con otros módulos
        """
        self.wallet_manager = wallet_manager
        self.price_tracker = DexScreenerPriceTracker(wallet_manager)
        
        # Configuración de análisis
        self.min_safe_liquidity = 10000  # USD mínimo para considerar "seguro"
        self.min_safe_volume = 5000  # USD mínimo de volumen para seguridad
        
        # Rangos de recomendación
        self.recommendation_thresholds = {
            'strong_buy': 80,
            'buy': 65,
            'hold': 50,
            'sell': 35,
            'avoid': 0
        }
        
        print("🎯 DexScreener Pump Analyzer inicializado")
        print(f"💰 Configuración: Liquidez segura ${self.min_safe_liquidity:,}")

    def analyze_token(self, token_address: str) -> Optional[PumpAnalysis]:
        """
        Realiza análisis completo de un token
        
        Args:
            token_address: Dirección del token a analizar
            
        Returns:
            PumpAnalysis con análisis completo o None si hay error
        """
        try:
            print(f"🔍 Analizando token: {token_address[:8]}...")
            
            # Obtener datos del token
            token_price = self.price_tracker.get_token_price(token_address, force_refresh=True)
            
            if not token_price:
                print(f"❌ No se pudo obtener datos del token")
                return None
            
            print(f"📊 Analizando {token_price.symbol} - ${token_price.price_usd:.10f}")
            
            # Realizar análisis de seguridad
            safety_score, risk_factors = self._analyze_safety(token_price)
            
            # Realizar análisis de potencial
            potential_score, positive_factors = self._analyze_potential(token_price)
            
            # Análisis técnico
            technical_analysis = self._perform_technical_analysis(token_price)
            
            # Análisis fundamental
            fundamental_analysis = self._perform_fundamental_analysis(token_price)
            
            # Generar recomendación
            recommendation = self._generate_recommendation(safety_score, potential_score)
            
            # Sugerencia de trading
            trading_suggestion = self._generate_trading_suggestion(
                token_price, safety_score, potential_score, recommendation
            )
            
            analysis = PumpAnalysis(
                token_price=token_price,
                safety_score=safety_score,
                potential_score=potential_score,
                recommendation=recommendation,
                risk_factors=risk_factors,
                positive_factors=positive_factors,
                technical_analysis=technical_analysis,
                fundamental_analysis=fundamental_analysis,
                trading_suggestion=trading_suggestion,
                analyzed_at=datetime.now()
            )
            
            self._print_analysis_summary(analysis)
            
            return analysis
            
        except Exception as e:
            print(f"❌ Error analizando token: {e}")
            return None

    def analyze_multiple_tokens(self, token_addresses: List[str]) -> List[PumpAnalysis]:
        """
        Analiza múltiples tokens y los ordena por potencial
        
        Args:
            token_addresses: Lista de direcciones de tokens
            
        Returns:
            Lista de análisis ordenados por potencial
        """
        print(f"📊 Analizando {len(token_addresses)} tokens...")
        
        analyses = []
        
        for i, token_address in enumerate(token_addresses, 1):
            print(f"\n🔄 Token {i}/{len(token_addresses)}")
            
            analysis = self.analyze_token(token_address)
            if analysis:
                analyses.append(analysis)
            
            # Pausa para no sobrecargar la API
            if i < len(token_addresses):
                time.sleep(3)
        
        # Ordenar por score combinado (seguridad + potencial)
        analyses.sort(key=lambda a: (a.safety_score + a.potential_score) / 2, reverse=True)
        
        print(f"\n✅ Análisis completado: {len(analyses)} tokens analizados")
        
        return analyses

    def get_top_pump_recommendations(self, limit: int = 10) -> List[PumpAnalysis]:
        """
        Obtiene las mejores recomendaciones de tokens de Pump.fun
        
        Args:
            limit: Número máximo de recomendaciones
            
        Returns:
            Lista de mejores análisis
        """
        try:
            print(f"🔥 Buscando top {limit} recomendaciones de Pump.fun...")
            
            # Obtener tokens trending
            trending_tokens = self.price_tracker.get_trending_pump_tokens(30)
            
            if not trending_tokens:
                print("❌ No se encontraron tokens trending")
                return []
            
            # Analizar los tokens trending
            token_addresses = [token.address for token in trending_tokens]
            analyses = self.analyze_multiple_tokens(token_addresses[:limit])
            
            # Filtrar solo recomendaciones positivas
            good_recommendations = [
                analysis for analysis in analyses 
                if analysis.recommendation in ['strong_buy', 'buy', 'hold']
            ]
            
            return good_recommendations[:limit]
            
        except Exception as e:
            print(f"❌ Error obteniendo recomendaciones: {e}")
            return []

    def _analyze_safety(self, token_price: TokenPrice) -> Tuple[float, List[str]]:
        """Analiza la seguridad del token"""
        safety_score = 0
        risk_factors = []
        
        # Análisis de liquidez (0-30 puntos)
        if token_price.liquidity_usd >= 100000:
            safety_score += 30
        elif token_price.liquidity_usd >= 50000:
            safety_score += 25
        elif token_price.liquidity_usd >= 20000:
            safety_score += 20
        elif token_price.liquidity_usd >= 10000:
            safety_score += 15
        elif token_price.liquidity_usd >= 5000:
            safety_score += 10
        else:
            risk_factors.append(f"Liquidez muy baja: ${token_price.liquidity_usd:,.0f}")
        
        # Análisis de volumen (0-25 puntos)
        if token_price.volume_24h >= 200000:
            safety_score += 25
        elif token_price.volume_24h >= 100000:
            safety_score += 20
        elif token_price.volume_24h >= 50000:
            safety_score += 15
        elif token_price.volume_24h >= 20000:
            safety_score += 10
        elif token_price.volume_24h >= 5000:
            safety_score += 5
        else:
            risk_factors.append(f"Volumen bajo: ${token_price.volume_24h:,.0f}")
        
        # Análisis de market cap (0-20 puntos)
        if 50000 <= token_price.market_cap <= 500000:
            safety_score += 20
        elif 20000 <= token_price.market_cap <= 10000000:
            safety_score += 15
        elif 5000 <= token_price.market_cap <= 20000000:
            safety_score += 10
        elif token_price.market_cap < 5000:
            risk_factors.append(f"Market cap extremadamente bajo: ${token_price.market_cap:,.0f}")
        
        # Análisis de DEX (0-15 puntos)
        if token_price.dex == 'pump':
            safety_score += 15
        else:
            risk_factors.append(f"No está en Pump.fun: {token_price.dex}")
        
        # Análisis de volatilidad (0-10 puntos)
        price_change = abs(token_price.price_change_24h)
        if price_change <= 20:
            safety_score += 10
        elif price_change <= 50:
            safety_score += 7
        elif price_change <= 100:
            safety_score += 3
        else:
            risk_factors.append(f"Volatilidad extrema: {token_price.price_change_24h:+.1f}%")
        
        return min(safety_score, 100), risk_factors

    def _analyze_potential(self, token_price: TokenPrice) -> Tuple[float, List[str]]:
        """Analiza el potencial de crecimiento del token"""
        potential_score = 0
        positive_factors = []
        
        # Market cap bajo = mayor potencial (0-30 puntos)
        if token_price.market_cap <= 100000:
            potential_score += 30
            positive_factors.append(f"Market cap muy bajo - alto potencial: ${token_price.market_cap:,.0f}")
        elif token_price.market_cap <= 500000:
            potential_score += 25
            positive_factors.append(f"Market cap bajo - buen potencial: ${token_price.market_cap:,.0f}")
        elif token_price.market_cap <= 2000000:
            potential_score += 20
        elif token_price.market_cap <= 10000000:
            potential_score += 15
        
        # Volumen alto = interés (0-25 puntos)
        if token_price.volume_24h >= 500000:
            potential_score += 25
            positive_factors.append(f"Volumen muy alto: ${token_price.volume_24h:,.0f}")
        elif token_price.volume_24h >= 200000:
            potential_score += 20
            positive_factors.append(f"Volumen alto: ${token_price.volume_24h:,.0f}")
        elif token_price.volume_24h >= 100000:
            potential_score += 15
        elif token_price.volume_24h >= 50000:
            potential_score += 10
        
        # Cambio de precio positivo (0-25 puntos)
        if token_price.price_change_24h >= 50:
            potential_score += 25
            positive_factors.append(f"Fuerte momentum alcista: +{token_price.price_change_24h:.1f}%")
        elif token_price.price_change_24h >= 20:
            potential_score += 20
            positive_factors.append(f"Momentum positivo: +{token_price.price_change_24h:.1f}%")
        elif token_price.price_change_24h >= 10:
            potential_score += 15
        elif token_price.price_change_24h >= 0:
            potential_score += 10
        
        # Estar en Pump.fun (0-20 puntos)
        if token_price.dex == 'pump':
            potential_score += 20
            positive_factors.append("Token de Pump.fun - ecosistema viral")
        
        return min(potential_score, 100), positive_factors

    def _perform_technical_analysis(self, token_price: TokenPrice) -> Dict[str, Any]:
        """Realiza análisis técnico básico"""
        analysis = {
            'price_momentum': 'neutral',
            'volume_trend': 'neutral',
            'liquidity_health': 'neutral',
            'volatility_level': 'medium'
        }
        
        # Momentum de precio
        if token_price.price_change_24h > 30:
            analysis['price_momentum'] = 'strong_bullish'
        elif token_price.price_change_24h > 10:
            analysis['price_momentum'] = 'bullish'
        elif token_price.price_change_24h < -30:
            analysis['price_momentum'] = 'strong_bearish'
        elif token_price.price_change_24h < -10:
            analysis['price_momentum'] = 'bearish'
        
        # Tendencia de volumen
        if token_price.volume_24h > 200000:
            analysis['volume_trend'] = 'very_high'
        elif token_price.volume_24h > 100000:
            analysis['volume_trend'] = 'high'
        elif token_price.volume_24h > 50000:
            analysis['volume_trend'] = 'medium'
        elif token_price.volume_24h > 10000:
            analysis['volume_trend'] = 'low'
        else:
            analysis['volume_trend'] = 'very_low'
        
        # Salud de liquidez
        if token_price.liquidity_usd > 100000:
            analysis['liquidity_health'] = 'excellent'
        elif token_price.liquidity_usd > 50000:
            analysis['liquidity_health'] = 'good'
        elif token_price.liquidity_usd > 20000:
            analysis['liquidity_health'] = 'adequate'
        elif token_price.liquidity_usd > 10000:
            analysis['liquidity_health'] = 'low'
        else:
            analysis['liquidity_health'] = 'critical'
        
        # Nivel de volatilidad
        price_change = abs(token_price.price_change_24h)
        if price_change > 100:
            analysis['volatility_level'] = 'extreme'
        elif price_change > 50:
            analysis['volatility_level'] = 'very_high'
        elif price_change > 25:
            analysis['volatility_level'] = 'high'
        elif price_change > 10:
            analysis['volatility_level'] = 'medium'
        else:
            analysis['volatility_level'] = 'low'
        
        return analysis

    def _perform_fundamental_analysis(self, token_price: TokenPrice) -> Dict[str, Any]:
        """Realiza análisis fundamental"""
        analysis = {
            'market_cap_category': '',
            'liquidity_category': '',
            'volume_category': '',
            'dex_ecosystem': token_price.dex,
            'growth_stage': '',
            'risk_category': ''
        }
        
        # Categoría de market cap
        if token_price.market_cap < 50000:
            analysis['market_cap_category'] = 'micro_cap'
            analysis['growth_stage'] = 'very_early'
        elif token_price.market_cap < 500000:
            analysis['market_cap_category'] = 'small_cap'
            analysis['growth_stage'] = 'early'
        elif token_price.market_cap < 5000000:
            analysis['market_cap_category'] = 'mid_cap'
            analysis['growth_stage'] = 'growth'
        else:
            analysis['market_cap_category'] = 'large_cap'
            analysis['growth_stage'] = 'mature'
        
        # Categoría de liquidez
        if token_price.liquidity_usd < 10000:
            analysis['liquidity_category'] = 'very_low'
        elif token_price.liquidity_usd < 50000:
            analysis['liquidity_category'] = 'low'
        elif token_price.liquidity_usd < 200000:
            analysis['liquidity_category'] = 'medium'
        else:
            analysis['liquidity_category'] = 'high'
        
        # Categoría de volumen
        if token_price.volume_24h < 10000:
            analysis['volume_category'] = 'very_low'
        elif token_price.volume_24h < 100000:
            analysis['volume_category'] = 'low'
        elif token_price.volume_24h < 500000:
            analysis['volume_category'] = 'medium'
        else:
            analysis['volume_category'] = 'high'
        
        # Categoría de riesgo general
        if (analysis['market_cap_category'] == 'micro_cap' and 
            analysis['liquidity_category'] in ['very_low', 'low']):
            analysis['risk_category'] = 'very_high'
        elif analysis['liquidity_category'] == 'very_low':
            analysis['risk_category'] = 'high'
        elif (analysis['liquidity_category'] == 'low' and 
              analysis['volume_category'] in ['very_low', 'low']):
            analysis['risk_category'] = 'medium_high'
        elif analysis['liquidity_category'] in ['medium', 'high']:
            analysis['risk_category'] = 'medium'
        else:
            analysis['risk_category'] = 'low'
        
        return analysis

    def _generate_recommendation(self, safety_score: float, potential_score: float) -> str:
        """Genera recomendación basada en scores"""
        combined_score = (safety_score * 0.6 + potential_score * 0.4)  # Peso mayor a seguridad
        
        for recommendation, threshold in self.recommendation_thresholds.items():
            if combined_score >= threshold:
                return recommendation
        
        return 'avoid'

    def _generate_trading_suggestion(self, token_price: TokenPrice, safety_score: float, 
                                   potential_score: float, recommendation: str) -> Dict[str, Any]:
        """Genera sugerencias específicas de trading"""
        suggestion = {
            'action': recommendation,
            'position_size': 'small',
            'entry_strategy': 'gradual',
            'stop_loss': None,
            'take_profit': None,
            'time_horizon': 'short',
            'notes': []
        }
        
        # Tamaño de posición basado en seguridad
        if safety_score >= 80:
            suggestion['position_size'] = 'medium'
        elif safety_score >= 60:
            suggestion['position_size'] = 'small'
        else:
            suggestion['position_size'] = 'very_small'
        
        # Estrategia de entrada
        if token_price.price_change_24h > 50:
            suggestion['entry_strategy'] = 'wait_for_pullback'
            suggestion['notes'].append("Precio muy alto - esperar retroceso")
        elif token_price.price_change_24h < -30:
            suggestion['entry_strategy'] = 'buy_the_dip'
            suggestion['notes'].append("Posible oportunidad de compra en caída")
        
        # Stop loss sugerido
        if recommendation in ['strong_buy', 'buy']:
            suggestion['stop_loss'] = f"{max(20, abs(token_price.price_change_24h) + 15):.0f}%"
        
        # Take profit sugerido
        if potential_score >= 70:
            suggestion['take_profit'] = "100-500%"
            suggestion['time_horizon'] = 'medium'
        elif potential_score >= 50:
            suggestion['take_profit'] = "50-200%"
        else:
            suggestion['take_profit'] = "20-100%"
        
        # Notas adicionales
        if token_price.liquidity_usd < 15000:
            suggestion['notes'].append("⚠️ Liquidez baja - cuidado con slippage")
        
        if token_price.volume_24h < 10000:
            suggestion['notes'].append("⚠️ Volumen bajo - difícil salida")
        
        if abs(token_price.price_change_24h) > 100:
            suggestion['notes'].append("⚠️ Extrema volatilidad - alto riesgo")
        
        return suggestion

    def _print_analysis_summary(self, analysis: PumpAnalysis):
        """Imprime resumen del análisis"""
        token = analysis.token_price
        
        print(f"\n📊 ANÁLISIS COMPLETO: {token.symbol}")
        print(f"💰 Precio: ${token.price_usd:.10f} ({token.price_change_24h:+.1f}%)")
        print(f"📈 Market Cap: ${token.market_cap:,.0f}")
        print(f"💧 Liquidez: ${token.liquidity_usd:,.0f}")
        print(f"📊 Volumen 24h: ${token.volume_24h:,.0f}")
        print(f"🔒 Score Seguridad: {analysis.safety_score:.1f}/100")
        print(f"🚀 Score Potencial: {analysis.potential_score:.1f}/100")
        print(f"📋 Recomendación: {analysis.recommendation.upper()}")
        
        if analysis.risk_factors:
            print(f"⚠️ Factores de Riesgo:")
            for factor in analysis.risk_factors[:3]:
                print(f"   • {factor}")
        
        if analysis.positive_factors:
            print(f"✅ Factores Positivos:")
            for factor in analysis.positive_factors[:3]:
                print(f"   • {factor}")
        
        suggestion = analysis.trading_suggestion
        print(f"💡 Sugerencia: {suggestion['action']} - Tamaño: {suggestion['position_size']}")
        
        if suggestion['notes']:
            print(f"📝 Notas: {suggestion['notes'][0]}")
        
        print("-" * 60) 