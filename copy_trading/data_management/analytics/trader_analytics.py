"""
Análisis de datos de traders
"""
from typing import Dict, Any, List
from datetime import datetime

from logging_system import AppLogger


class TraderAnalytics:
    """Análisis de datos de traders"""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

    def analyze_trader_performance(self, trader_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analiza el rendimiento de un trader"""
        try:
            analysis = {
                'trader_wallet': trader_data.get('trader_wallet'),
                'analysis_timestamp': datetime.now().isoformat(),
                'metrics': {}
            }

            # Análisis de volumen
            total_volume = trader_data.get('total_volume_sol', 0)
            analysis['metrics']['total_volume_sol'] = total_volume
            analysis['metrics']['volume_category'] = self._categorize_volume(total_volume)

            # Análisis de PnL
            total_pnl = trader_data.get('total_pnl_sol', 0)
            analysis['metrics']['total_pnl_sol'] = total_pnl
            analysis['metrics']['pnl_performance'] = self._analyze_pnl_performance(total_pnl)

            # Análisis de trades
            total_trades = trader_data.get('total_trades', 0)
            analysis['metrics']['total_trades'] = total_trades
            analysis['metrics']['trade_frequency'] = self._analyze_trade_frequency(total_trades)

            # Análisis de win rate
            win_rate = trader_data.get('win_rate', 0)
            analysis['metrics']['win_rate'] = win_rate
            analysis['metrics']['success_level'] = self._analyze_win_rate(win_rate)

            # Análisis de tokens
            unique_tokens = trader_data.get('unique_tokens', 0)
            analysis['metrics']['unique_tokens'] = unique_tokens
            analysis['metrics']['diversification'] = self._analyze_diversification(unique_tokens)

            # Score general
            analysis['metrics']['overall_score'] = self._calculate_trader_score(analysis['metrics'])

            return analysis

        except Exception as e:
            self._logger.error(f"Error analizando trader performance: {e}")
            return {'error': str(e)}

    def analyze_trader_risk(self, trader_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analiza el riesgo de un trader"""
        try:
            risk_analysis = {
                'trader_wallet': trader_data.get('trader_wallet'),
                'risk_timestamp': datetime.now().isoformat(),
                'risk_factors': {}
            }

            # Factor de concentración
            unique_tokens = trader_data.get('unique_tokens', 0)
            risk_analysis['risk_factors']['concentration_risk'] = self._calculate_concentration_risk(unique_tokens)

            # Factor de volatilidad de PnL
            total_pnl = trader_data.get('total_pnl_sol', 0)
            risk_analysis['risk_factors']['pnl_volatility_risk'] = self._calculate_pnl_volatility_risk(total_pnl)

            # Factor de frecuencia de trading
            total_trades = trader_data.get('total_trades', 0)
            risk_analysis['risk_factors']['overtrading_risk'] = self._calculate_overtrading_risk(total_trades)

            # Factor de consistencia
            win_rate = trader_data.get('win_rate', 0)
            risk_analysis['risk_factors']['consistency_risk'] = self._calculate_consistency_risk(win_rate)

            # Riesgo total
            risk_analysis['total_risk_score'] = self._calculate_trader_risk_total(risk_analysis['risk_factors'])
            risk_analysis['risk_level'] = self._categorize_trader_risk_level(risk_analysis['total_risk_score'])

            return risk_analysis

        except Exception as e:
            self._logger.error(f"Error analizando trader risk: {e}")
            return {'error': str(e)}

    def compare_traders(self, traders_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compara múltiples traders"""
        try:
            comparison = {
                'comparison_timestamp': datetime.now().isoformat(),
                'traders_count': len(traders_data),
                'rankings': {},
                'statistics': {}
            }

            if not traders_data:
                return comparison

            # Rankings por volumen
            volume_rankings = sorted(
                traders_data, 
                key=lambda x: x.get('total_volume_sol', 0), 
                reverse=True
            )
            comparison['rankings']['by_volume'] = [
                {
                    'trader_wallet': trader.get('trader_wallet'),
                    'total_volume_sol': trader.get('total_volume_sol', 0)
                }
                for trader in volume_rankings
            ]

            # Rankings por PnL
            pnl_rankings = sorted(
                traders_data,
                key=lambda x: x.get('total_pnl_sol', 0),
                reverse=True
            )
            comparison['rankings']['by_pnl'] = [
                {
                    'trader_wallet': trader.get('trader_wallet'),
                    'total_pnl_sol': trader.get('total_pnl_sol', 0)
                }
                for trader in pnl_rankings
            ]

            # Rankings por win rate
            winrate_rankings = sorted(
                traders_data,
                key=lambda x: x.get('win_rate', 0),
                reverse=True
            )
            comparison['rankings']['by_winrate'] = [
                {
                    'trader_wallet': trader.get('trader_wallet'),
                    'win_rate': trader.get('win_rate', 0)
                }
                for trader in winrate_rankings
            ]

            # Estadísticas generales
            volumes = [trader.get('total_volume_sol', 0) for trader in traders_data]
            pnls = [trader.get('total_pnl_sol', 0) for trader in traders_data]
            win_rates = [trader.get('win_rate', 0) for trader in traders_data]

            comparison['statistics']['avg_volume'] = sum(volumes) / len(volumes) if volumes else 0
            comparison['statistics']['avg_pnl'] = sum(pnls) / len(pnls) if pnls else 0
            comparison['statistics']['avg_winrate'] = sum(win_rates) / len(win_rates) if win_rates else 0

            return comparison

        except Exception as e:
            self._logger.error(f"Error comparando traders: {e}")
            return {'error': str(e)}

    def get_top_traders(self, traders_data: List[Dict[str, Any]], 
                        limit: int = 10, 
                        sort_by: str = 'total_volume_sol') -> List[Dict[str, Any]]:
        """Obtiene los mejores traders según criterio"""
        try:
            if not traders_data:
                return []

            # Ordenar por criterio
            sorted_traders = sorted(
                traders_data,
                key=lambda x: x.get(sort_by, 0),
                reverse=True
            )

            # Retornar top N
            return sorted_traders[:limit]

        except Exception as e:
            self._logger.error(f"Error obteniendo top traders: {e}")
            return []

    def _categorize_volume(self, volume: float) -> str:
        """Categoriza el volumen de trading"""
        if volume >= 10000:
            return 'whale'
        elif volume >= 1000:
            return 'high'
        elif volume >= 100:
            return 'medium'
        elif volume >= 10:
            return 'low'
        else:
            return 'very_low'

    def _analyze_pnl_performance(self, pnl: float) -> str:
        """Analiza el rendimiento de PnL"""
        if pnl >= 1000:
            return 'excellent'
        elif pnl >= 100:
            return 'good'
        elif pnl >= 10:
            return 'moderate'
        elif pnl >= 0:
            return 'break_even'
        else:
            return 'losing'

    def _analyze_trade_frequency(self, total_trades: int) -> str:
        """Analiza la frecuencia de trading"""
        if total_trades >= 1000:
            return 'very_high'
        elif total_trades >= 500:
            return 'high'
        elif total_trades >= 100:
            return 'moderate'
        elif total_trades >= 50:
            return 'low'
        else:
            return 'very_low'

    def _analyze_win_rate(self, win_rate: float) -> str:
        """Analiza el win rate"""
        if win_rate >= 80:
            return 'excellent'
        elif win_rate >= 60:
            return 'good'
        elif win_rate >= 50:
            return 'average'
        elif win_rate >= 40:
            return 'below_average'
        else:
            return 'poor'

    def _analyze_diversification(self, unique_tokens: int) -> str:
        """Analiza la diversificación"""
        if unique_tokens >= 50:
            return 'highly_diversified'
        elif unique_tokens >= 20:
            return 'diversified'
        elif unique_tokens >= 10:
            return 'moderately_diversified'
        elif unique_tokens >= 5:
            return 'low_diversification'
        else:
            return 'concentrated'

    def _calculate_trader_score(self, metrics: Dict[str, Any]) -> float:
        """Calcula un score general del trader"""
        score = 0.0

        # Score por volumen (0-20 puntos)
        volume_category = metrics.get('volume_category', 'very_low')
        volume_scores = {'whale': 20, 'high': 15, 'medium': 10, 'low': 5, 'very_low': 1}
        score += volume_scores.get(volume_category, 0)

        # Score por PnL (0-25 puntos)
        pnl_performance = metrics.get('pnl_performance', 'losing')
        pnl_scores = {'excellent': 25, 'good': 20, 'moderate': 15, 'break_even': 10, 'losing': 5}
        score += pnl_scores.get(pnl_performance, 0)

        # Score por win rate (0-25 puntos)
        success_level = metrics.get('success_level', 'poor')
        success_scores = {'excellent': 25, 'good': 20, 'average': 15, 'below_average': 10, 'poor': 5}
        score += success_scores.get(success_level, 0)

        # Score por diversificación (0-15 puntos)
        diversification = metrics.get('diversification', 'concentrated')
        div_scores = {'highly_diversified': 15, 'diversified': 12, 'moderately_diversified': 8, 'low_diversification': 4, 'concentrated': 1}
        score += div_scores.get(diversification, 0)

        # Score por frecuencia (0-15 puntos)
        trade_frequency = metrics.get('trade_frequency', 'very_low')
        freq_scores = {'very_high': 15, 'high': 12, 'moderate': 8, 'low': 4, 'very_low': 1}
        score += freq_scores.get(trade_frequency, 0)
        
        return score

    def _calculate_concentration_risk(self, unique_tokens: int) -> float:
        """Calcula el riesgo de concentración (0-1)"""
        if unique_tokens >= 50:
            return 0.1
        elif unique_tokens >= 20:
            return 0.3
        elif unique_tokens >= 10:
            return 0.5
        elif unique_tokens >= 5:
            return 0.7
        else:
            return 1.0

    def _calculate_pnl_volatility_risk(self, total_pnl: float) -> float:
        """Calcula el riesgo de volatilidad de PnL (0-1)"""
        if total_pnl >= 1000:
            return 0.1
        elif total_pnl >= 100:
            return 0.3
        elif total_pnl >= 0:
            return 0.6
        else:
            return 1.0

    def _calculate_overtrading_risk(self, total_trades: int) -> float:
        """Calcula el riesgo de overtrading (0-1)"""
        if total_trades >= 1000:
            return 1.0
        elif total_trades >= 500:
            return 0.8
        elif total_trades >= 100:
            return 0.5
        elif total_trades >= 50:
            return 0.3
        else:
            return 0.1

    def _calculate_consistency_risk(self, win_rate: float) -> float:
        """Calcula el riesgo de consistencia (0-1)"""
        if win_rate >= 80:
            return 0.1
        elif win_rate >= 60:
            return 0.3
        elif win_rate >= 50:
            return 0.5
        elif win_rate >= 40:
            return 0.7
        else:
            return 1.0

    def _calculate_trader_risk_total(self, risk_factors: Dict[str, float]) -> float:
        """Calcula el riesgo total del trader"""
        weights = {
            'concentration_risk': 0.3,
            'pnl_volatility_risk': 0.3,
            'overtrading_risk': 0.2,
            'consistency_risk': 0.2
        }

        total_risk = 0.0
        for factor, weight in weights.items():
            total_risk += risk_factors.get(factor, 0) * weight

        return min(total_risk, 1.0)

    def _categorize_trader_risk_level(self, risk_score: float) -> str:
        """Categoriza el nivel de riesgo del trader"""
        if risk_score <= 0.3:
            return 'low'
        elif risk_score <= 0.6:
            return 'medium'
        else:
            return 'high'
