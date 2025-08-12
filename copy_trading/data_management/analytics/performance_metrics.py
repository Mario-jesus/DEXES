"""
Métricas de rendimiento del sistema
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta

from logging_system import AppLogger


class PerformanceMetrics:
    """Métricas de rendimiento del sistema"""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)
        self.metrics_history: List[Dict[str, Any]] = []

    def calculate_system_performance(self, system_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula el rendimiento general del sistema"""
        try:
            performance = {
                'timestamp': datetime.now().isoformat(),
                'metrics': {}
            }

            # Métricas de trades
            trades_processed = system_data.get('trades_processed', 0)
            trades_executed = system_data.get('trades_executed', 0)

            performance['metrics']['trades_processed'] = trades_processed
            performance['metrics']['trades_executed'] = trades_executed
            performance['metrics']['execution_rate'] = self._calculate_execution_rate(trades_processed, trades_executed)

            # Métricas de volumen
            total_volume = system_data.get('total_volume_sol', 0)
            performance['metrics']['total_volume_sol'] = total_volume
            performance['metrics']['avg_trade_size'] = self._calculate_avg_trade_size(total_volume, trades_executed)

            # Métricas de PnL
            total_pnl = system_data.get('total_pnl', 0)
            performance['metrics']['total_pnl'] = total_pnl
            performance['metrics']['roi_percentage'] = self._calculate_roi(total_pnl, total_volume)

            # Métricas de latencia
            avg_latency = system_data.get('average_latency_ms', 0)
            performance['metrics']['average_latency_ms'] = avg_latency
            performance['metrics']['latency_performance'] = self._categorize_latency(avg_latency)

            # Métricas de uptime
            uptime_seconds = system_data.get('uptime_seconds', 0)
            performance['metrics']['uptime_seconds'] = uptime_seconds
            performance['metrics']['uptime_hours'] = uptime_seconds / 3600
            performance['metrics']['uptime_percentage'] = self._calculate_uptime_percentage(uptime_seconds)

            # Score general
            performance['metrics']['overall_performance_score'] = self._calculate_performance_score(performance['metrics'])

            # Guardar en historial
            self.metrics_history.append(performance)

            return performance

        except Exception as e:
            self._logger.error(f"Error calculando performance del sistema: {e}")
            return {'error': str(e)}

    def calculate_trader_performance_metrics(self, traders_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calcula métricas de rendimiento de traders"""
        try:
            if not traders_data:
                return {'error': 'No hay datos de traders'}
            
            metrics = {
                'timestamp': datetime.now().isoformat(),
                'trader_count': len(traders_data),
                'aggregate_metrics': {},
                'performance_distribution': {}
            }

            # Métricas agregadas
            total_volume = sum(trader.get('total_volume_sol', 0) for trader in traders_data)
            total_pnl = sum(trader.get('total_pnl_sol', 0) for trader in traders_data)
            total_trades = sum(trader.get('total_trades', 0) for trader in traders_data)

            metrics['aggregate_metrics']['total_volume_sol'] = total_volume
            metrics['aggregate_metrics']['total_pnl_sol'] = total_pnl
            metrics['aggregate_metrics']['total_trades'] = total_trades
            metrics['aggregate_metrics']['avg_volume_per_trader'] = total_volume / len(traders_data)
            metrics['aggregate_metrics']['avg_pnl_per_trader'] = total_pnl / len(traders_data)
            metrics['aggregate_metrics']['avg_trades_per_trader'] = total_trades / len(traders_data)

            # Distribución de rendimiento
            win_rates = [trader.get('win_rate', 0) for trader in traders_data]
            metrics['performance_distribution']['avg_win_rate'] = sum(win_rates) / len(win_rates)
            metrics['performance_distribution']['win_rate_std'] = self._calculate_std(win_rates)
            
            # Categorización de traders
            profitable_traders = [t for t in traders_data if t.get('total_pnl_sol', 0) > 0]
            metrics['performance_distribution']['profitable_traders_count'] = len(profitable_traders)
            metrics['performance_distribution']['profitable_traders_percentage'] = len(profitable_traders) / len(traders_data) * 100

            return metrics

        except Exception as e:
            self._logger.error(f"Error calculando métricas de traders: {e}")
            return {'error': str(e)}

    def calculate_efficiency_metrics(self, system_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula métricas de eficiencia del sistema"""
        try:
            efficiency = {
                'timestamp': datetime.now().isoformat(),
                'efficiency_metrics': {}
            }

            # Eficiencia de ejecución
            trades_processed = system_data.get('trades_processed', 0)
            trades_executed = system_data.get('trades_executed', 0)
            efficiency['efficiency_metrics']['execution_efficiency'] = self._calculate_execution_efficiency(trades_processed, trades_executed)

            # Eficiencia de latencia
            avg_latency = system_data.get('average_latency_ms', 0)
            efficiency['efficiency_metrics']['latency_efficiency'] = self._calculate_latency_efficiency(avg_latency)

            # Eficiencia de recursos
            uptime_seconds = system_data.get('uptime_seconds', 0)
            efficiency['efficiency_metrics']['uptime_efficiency'] = self._calculate_uptime_efficiency(uptime_seconds)

            # Eficiencia general
            efficiency['efficiency_metrics']['overall_efficiency'] = self._calculate_overall_efficiency(efficiency['efficiency_metrics'])

            return efficiency

        except Exception as e:
            self._logger.error(f"Error calculando métricas de eficiencia: {e}")
            return {'error': str(e)}

    def get_performance_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Obtiene tendencias de rendimiento"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)

            # Filtrar métricas del período
            recent_metrics = [
                m for m in self.metrics_history
                if datetime.fromisoformat(m['timestamp']) >= cutoff_time
            ]

            if not recent_metrics:
                return {'error': 'No hay datos recientes'}

            trends = {
                'period_hours': hours,
                'data_points': len(recent_metrics),
                'trends': {}
            }

            # Calcular tendencias
            execution_rates = [m['metrics'].get('execution_rate', 0) for m in recent_metrics]
            trends['trends']['execution_rate_trend'] = self._calculate_trend(execution_rates)

            latencies = [m['metrics'].get('average_latency_ms', 0) for m in recent_metrics]
            trends['trends']['latency_trend'] = self._calculate_trend(latencies)

            volumes = [m['metrics'].get('total_volume_sol', 0) for m in recent_metrics]
            trends['trends']['volume_trend'] = self._calculate_trend(volumes)

            return trends

        except Exception as e:
            self._logger.error(f"Error calculando tendencias: {e}")
            return {'error': str(e)}

    def _calculate_execution_rate(self, processed: int, executed: int) -> float:
        """Calcula la tasa de ejecución"""
        if processed == 0:
            return 0.0
        return (executed / processed) * 100

    def _calculate_avg_trade_size(self, total_volume: float, trades_count: int) -> float:
        """Calcula el tamaño promedio de trade"""
        if trades_count == 0:
            return 0.0
        return total_volume / trades_count

    def _calculate_roi(self, total_pnl: float, total_volume: float) -> float:
        """Calcula el ROI"""
        if total_volume == 0:
            return 0.0
        return (total_pnl / total_volume) * 100

    def _categorize_latency(self, latency_ms: float) -> str:
        """Categoriza la latencia"""
        if latency_ms <= 100:
            return 'excellent'
        elif latency_ms <= 500:
            return 'good'
        elif latency_ms <= 1000:
            return 'acceptable'
        else:
            return 'poor'

    def _calculate_uptime_percentage(self, uptime_seconds: float) -> float:
        """Calcula el porcentaje de uptime"""
        # Asumiendo que el sistema debería estar activo 24/7
        total_expected_seconds = 24 * 3600  # 24 horas
        return min((uptime_seconds / total_expected_seconds) * 100, 100)

    def _calculate_performance_score(self, metrics: Dict[str, Any]) -> float:
        """Calcula un score general de rendimiento"""
        score = 0.0

        # Score por tasa de ejecución (0-25 puntos)
        execution_rate = metrics.get('execution_rate', 0)
        score += min(execution_rate / 4, 25)  # 100% = 25 puntos

        # Score por latencia (0-25 puntos)
        latency_performance = metrics.get('latency_performance', 'poor')
        latency_scores = {'excellent': 25, 'good': 20, 'acceptable': 15, 'poor': 5}
        score += latency_scores.get(latency_performance, 0)

        # Score por uptime (0-25 puntos)
        uptime_percentage = metrics.get('uptime_percentage', 0)
        score += min(uptime_percentage / 4, 25)  # 100% = 25 puntos

        # Score por ROI (0-25 puntos)
        roi = abs(metrics.get('roi_percentage', 0))
        score += min(roi, 25)  # Máximo 25 puntos
        
        return score

    def _calculate_execution_efficiency(self, processed: int, executed: int) -> float:
        """Calcula la eficiencia de ejecución"""
        if processed == 0:
            return 0.0
        return (executed / processed) * 100

    def _calculate_latency_efficiency(self, latency_ms: float) -> float:
        """Calcula la eficiencia de latencia"""
        if latency_ms <= 100:
            return 100.0
        elif latency_ms <= 1000:
            return max(100 - (latency_ms - 100) / 9, 0)  # Decrece linealmente
        else:
            return 0.0

    def _calculate_uptime_efficiency(self, uptime_seconds: float) -> float:
        """Calcula la eficiencia de uptime"""
        expected_uptime = 24 * 3600  # 24 horas
        return min((uptime_seconds / expected_uptime) * 100, 100)

    def _calculate_overall_efficiency(self, efficiency_metrics: Dict[str, float]) -> float:
        """Calcula la eficiencia general"""
        weights = {
            'execution_efficiency': 0.4,
            'latency_efficiency': 0.3,
            'uptime_efficiency': 0.3
        }

        total_efficiency = 0.0
        for metric, weight in weights.items():
            total_efficiency += efficiency_metrics.get(metric, 0) * weight

        return total_efficiency

    def _calculate_std(self, values: List[float]) -> float:
        """Calcula la desviación estándar"""
        if not values:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    def _calculate_trend(self, values: List[float]) -> str:
        """Calcula la tendencia de una serie de valores"""
        if len(values) < 2:
            return 'stable'

        # Calcular pendiente promedio
        slopes = []
        for i in range(1, len(values)):
            slope = values[i] - values[i-1]
            slopes.append(slope)

        avg_slope = sum(slopes) / len(slopes)

        if avg_slope > 0.1:
            return 'increasing'
        elif avg_slope < -0.1:
            return 'decreasing'
        else:
            return 'stable'

    def clear_history(self) -> None:
        """Limpia el historial de métricas"""
        self.metrics_history.clear()
        self._logger.info("Historial de métricas limpiado")

    def get_history_size(self) -> int:
        """Obtiene el tamaño del historial"""
        return len(self.metrics_history)
