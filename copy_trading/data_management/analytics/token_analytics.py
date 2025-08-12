"""
Análisis de datos de tokens
"""
from typing import Dict, Any, List
from datetime import datetime

from logging_system import AppLogger


class TokenAnalytics:
    """Análisis de datos de tokens"""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

    def analyze_token_performance(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analiza el rendimiento de un token"""
        try:
            analysis = {
                'token_address': token_data.get('token_address'),
                'analysis_timestamp': datetime.now().isoformat(),
                'metrics': {}
            }

            # Análisis de volumen
            volume_24h = token_data.get('volume_24h', 0)
            analysis['metrics']['volume_24h'] = volume_24h
            analysis['metrics']['volume_category'] = self._categorize_volume(volume_24h)

            # Análisis de precio
            price_change_24h = token_data.get('price_change_24h', 0)
            analysis['metrics']['price_change_24h'] = price_change_24h
            analysis['metrics']['price_trend'] = self._analyze_price_trend(price_change_24h)

            # Análisis de liquidez
            liquidity = token_data.get('liquidity', 0)
            analysis['metrics']['liquidity'] = liquidity
            analysis['metrics']['liquidity_risk'] = self._assess_liquidity_risk(liquidity)

            # Análisis de traders
            num_traders = token_data.get('num_traders', 0)
            analysis['metrics']['num_traders'] = num_traders
            analysis['metrics']['trader_activity'] = self._analyze_trader_activity(num_traders)

            # Score general
            analysis['metrics']['overall_score'] = self._calculate_overall_score(analysis['metrics'])

            return analysis

        except Exception as e:
            self._logger.error(f"Error analizando token performance: {e}")
            return {'error': str(e)}

    def analyze_token_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analiza el riesgo de un token"""
        try:
            risk_analysis = {
                'token_address': token_data.get('token_address'),
                'risk_timestamp': datetime.now().isoformat(),
                'risk_factors': {}
            }

            # Factor de liquidez
            liquidity = token_data.get('liquidity', 0)
            risk_analysis['risk_factors']['liquidity_risk'] = self._calculate_liquidity_risk(liquidity)

            # Factor de volatilidad
            price_change_24h = abs(token_data.get('price_change_24h', 0))
            risk_analysis['risk_factors']['volatility_risk'] = self._calculate_volatility_risk(price_change_24h)

            # Factor de concentración de traders
            num_traders = token_data.get('num_traders', 0)
            risk_analysis['risk_factors']['concentration_risk'] = self._calculate_concentration_risk(num_traders)

            # Riesgo total
            risk_analysis['total_risk_score'] = self._calculate_total_risk(risk_analysis['risk_factors'])
            risk_analysis['risk_level'] = self._categorize_risk_level(risk_analysis['total_risk_score'])

            return risk_analysis

        except Exception as e:
            self._logger.error(f"Error analizando token risk: {e}")
            return {'error': str(e)}

    def compare_tokens(self, tokens_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compara múltiples tokens"""
        try:
            comparison = {
                'comparison_timestamp': datetime.now().isoformat(),
                'tokens_count': len(tokens_data),
                'rankings': {},
                'statistics': {}
            }

            if not tokens_data:
                return comparison

            # Rankings por volumen
            volume_rankings = sorted(
                tokens_data, 
                key=lambda x: x.get('volume_24h', 0), 
                reverse=True
            )
            comparison['rankings']['by_volume'] = [
                {
                    'token_address': token.get('token_address'),
                    'volume_24h': token.get('volume_24h', 0)
                }
                for token in volume_rankings
            ]

            # Rankings por cambio de precio
            price_rankings = sorted(
                tokens_data,
                key=lambda x: abs(x.get('price_change_24h', 0)),
                reverse=True
            )
            comparison['rankings']['by_volatility'] = [
                {
                    'token_address': token.get('token_address'),
                    'price_change_24h': token.get('price_change_24h', 0)
                }
                for token in price_rankings
            ]

            # Estadísticas generales
            volumes = [token.get('volume_24h', 0) for token in tokens_data]
            comparison['statistics']['avg_volume'] = sum(volumes) / len(volumes) if volumes else 0
            comparison['statistics']['max_volume'] = max(volumes) if volumes else 0
            comparison['statistics']['min_volume'] = min(volumes) if volumes else 0

            return comparison

        except Exception as e:
            self._logger.error(f"Error comparando tokens: {e}")
            return {'error': str(e)}

    def _categorize_volume(self, volume: float) -> str:
        """Categoriza el volumen de trading"""
        if volume >= 1000000:
            return 'high'
        elif volume >= 100000:
            return 'medium'
        elif volume >= 10000:
            return 'low'
        else:
            return 'very_low'

    def _analyze_price_trend(self, price_change: float) -> str:
        """Analiza la tendencia del precio"""
        if price_change > 10:
            return 'strong_bullish'
        elif price_change > 5:
            return 'bullish'
        elif price_change > -5:
            return 'neutral'
        elif price_change > -10:
            return 'bearish'
        else:
            return 'strong_bearish'

    def _assess_liquidity_risk(self, liquidity: float) -> str:
        """Evalúa el riesgo de liquidez"""
        if liquidity >= 100000:
            return 'low'
        elif liquidity >= 10000:
            return 'medium'
        else:
            return 'high'

    def _analyze_trader_activity(self, num_traders: int) -> str:
        """Analiza la actividad de traders"""
        if num_traders >= 100:
            return 'very_active'
        elif num_traders >= 50:
            return 'active'
        elif num_traders >= 20:
            return 'moderate'
        else:
            return 'low'

    def _calculate_overall_score(self, metrics: Dict[str, Any]) -> float:
        """Calcula un score general del token"""
        score = 0.0

        # Score por volumen (0-25 puntos)
        volume_category = metrics.get('volume_category', 'very_low')
        volume_scores = {'high': 25, 'medium': 15, 'low': 8, 'very_low': 2}
        score += volume_scores.get(volume_category, 0)

        # Score por liquidez (0-25 puntos)
        liquidity_risk = metrics.get('liquidity_risk', 'high')
        liquidity_scores = {'low': 25, 'medium': 15, 'high': 5}
        score += liquidity_scores.get(liquidity_risk, 0)

        # Score por actividad de traders (0-25 puntos)
        trader_activity = metrics.get('trader_activity', 'low')
        trader_scores = {'very_active': 25, 'active': 20, 'moderate': 12, 'low': 5}
        score += trader_scores.get(trader_activity, 0)

        # Score por estabilidad de precio (0-25 puntos)
        price_trend = metrics.get('price_trend', 'neutral')
        price_scores = {'neutral': 25, 'bullish': 20, 'bearish': 15, 'strong_bullish': 10, 'strong_bearish': 5}
        score += price_scores.get(price_trend, 0)

        return score

    def _calculate_liquidity_risk(self, liquidity: float) -> float:
        """Calcula el riesgo de liquidez (0-1)"""
        if liquidity >= 100000:
            return 0.1
        elif liquidity >= 50000:
            return 0.3
        elif liquidity >= 10000:
            return 0.6
        else:
            return 1.0

    def _calculate_volatility_risk(self, price_change: float) -> float:
        """Calcula el riesgo de volatilidad (0-1)"""
        if price_change <= 5:
            return 0.1
        elif price_change <= 15:
            return 0.4
        elif price_change <= 30:
            return 0.7
        else:
            return 1.0

    def _calculate_concentration_risk(self, num_traders: int) -> float:
        """Calcula el riesgo de concentración (0-1)"""
        if num_traders >= 100:
            return 0.1
        elif num_traders >= 50:
            return 0.3
        elif num_traders >= 20:
            return 0.6
        else:
            return 1.0

    def _calculate_total_risk(self, risk_factors: Dict[str, float]) -> float:
        """Calcula el riesgo total"""
        weights = {
            'liquidity_risk': 0.4,
            'volatility_risk': 0.3,
            'concentration_risk': 0.3
        }

        total_risk = 0.0
        for factor, weight in weights.items():
            total_risk += risk_factors.get(factor, 0) * weight

        return min(total_risk, 1.0)

    def _categorize_risk_level(self, risk_score: float) -> str:
        """Categoriza el nivel de riesgo"""
        if risk_score <= 0.3:
            return 'low'
        elif risk_score <= 0.6:
            return 'medium'
        else:
            return 'high'
