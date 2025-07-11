# -*- coding: utf-8 -*-
"""
Callback especializado para Copy Trading Mini
"""
import uuid
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from .config import CopyTradingConfig
from .position_queue import Position, PositionSide, PositionQueue
from .validation import ValidationEngine
from .logger import CopyTradingLogger
from .notifications import NotificationManager


class CopyTradingCallback:
    """Callback para procesar trades y replicarlos automáticamente"""

    def __init__(self, 
                    config: CopyTradingConfig,
                    position_queue: PositionQueue,
                    validation_engine: ValidationEngine,
                    logger: CopyTradingLogger,
                    trade_executor: Optional[Callable] = None,
                    notification_manager: Optional[NotificationManager] = None):
        """
        Inicializa el callback
        
        Args:
            config: Configuración del sistema
            position_queue: Cola de posiciones
            validation_engine: Motor de validaciones
            logger: Logger del sistema
            trade_executor: Función para ejecutar trades
        """
        self.config = config
        self.position_queue = position_queue
        self.validation_engine = validation_engine
        self.logger = logger
        self.trade_executor = trade_executor
        self.notification_manager = notification_manager

        # Estadísticas
        self.stats = {
            'trades_received': 0,
            'trades_validated': 0,
            'trades_queued': 0,
            'trades_rejected': 0,
            'last_trade_time': None
        }

        # Cache de trades procesados para evitar duplicados
        self.processed_signatures = set()
        self.signature_cache_size = 1000

    def _validate_trade_info(self, trade_info: dict) -> bool:
        """
        Valida que el trade tenga toda la información necesaria
        
        Args:
            trade_info: Información del trade
            
        Returns:
            True si el trade es válido
        """
        required_fields = ['trader_wallet', 'token_address', 'amount', 'side']

        # Verificar campos requeridos
        for field in required_fields:
            if field not in trade_info:
                self.logger.warning(f"Campo requerido faltante: {field}")
                return False

        # Validar tipos de datos
        if not isinstance(trade_info['trader_wallet'], str):
            self.logger.warning("trader_wallet debe ser string")
            return False

        if not isinstance(trade_info['token_address'], str):
            self.logger.warning("token_address debe ser string")
            return False

        if not isinstance(trade_info['amount'], (int, float)):
            self.logger.warning("amount debe ser numérico")
            return False

        if not isinstance(trade_info['side'], str):
            self.logger.warning("side debe ser string")
            return False

        # Validar valores
        if trade_info['amount'] <= 0:
            self.logger.warning("amount debe ser mayor a 0")
            return False

        if trade_info['side'].upper() not in ['BUY', 'SELL']:
            self.logger.warning("side debe ser 'buy' o 'sell'")
            return False

        # Verificar si es un trader que seguimos
        if trade_info['trader_wallet'] not in self.config.traders:
            self.logger.debug(f"Trader no seguido: {trade_info['trader_wallet']}")
            return False

        return True

    def _transform_pumpfun_trade(self, data: dict) -> dict:
        """
        Transforma el formato de trade de PumpFun al formato interno
        
        Args:
            data: Datos del trade en formato PumpFun
            
        Returns:
            Diccionario con el formato interno
        """
        try:
            # Extraer información del token desde el mint address
            token_address = data.get('mint', '')
            token_name = f"Token {token_address[:8]}..." if token_address else "Token Desconocido"
            token_symbol = token_address[:4].upper() if token_address else "UNKN"

            # Obtener el monto original del trade
            original_amount = float(data.get('solAmount', 0))

            # Calcular el monto a copiar según la configuración
            trader_wallet = data.get('traderPublicKey', '')
            copy_amount = self.config.calculate_copy_amount(trader_wallet, original_amount)

            return {
                'trader_wallet': trader_wallet,
                'token_address': token_address,
                'token_name': token_name,
                'token_symbol': token_symbol,
                'amount': copy_amount,  # Usar el monto calculado, no el original
                'original_amount': original_amount,  # Guardar el monto original para referencia
                'side': data.get('txType', '').lower(),
                # Datos adicionales que pueden ser útiles
                'token_amount': data.get('tokenAmount'),
                'signature': data.get('signature'),
                'pool': data.get('pool'),
                'market_cap': data.get('marketCapSol')
            }
        except Exception as e:
            self.logger.error(f"Error transformando datos de trade: {e}")
            return {}

    async def __call__(self, data: dict) -> None:
        """
        Procesa un trade recibido
        
        Args:
            data: Datos del trade en formato PumpFun
        """
        try:
            # Incrementar contador
            self.stats['trades_received'] += 1

            # Transformar formato
            trade_info = self._transform_pumpfun_trade(data)

            # Validar trade
            if not self._validate_trade_info(trade_info):
                self.logger.warning(f"Trade inválido recibido: {data}")

                # Notificar trade inválido
                if self.notification_manager:
                    error_msg = "Trade inválido o incompleto"
                    if not trade_info:
                        error_msg = "Error transformando datos del trade"
                    elif 'trader_wallet' not in trade_info:
                        error_msg = "Trader no especificado"
                    elif trade_info['trader_wallet'] not in self.config.traders:
                        error_msg = "Trader no seguido"

                    await self.notification_manager.notify_trade({
                        'side': trade_info.get('side', 'unknown'),
                        'token_address': trade_info.get('token_address', 'unknown'),
                        'token_name': trade_info.get('token_name', 'Token Desconocido'),
                        'token_symbol': trade_info.get('token_symbol', 'UNKN'),
                        'amount': trade_info.get('amount', 0),
                        'status': 'failed',
                        'error': error_msg
                    })
                return

            # Extraer información
            trader_wallet = trade_info['trader_wallet']
            token_address = trade_info['token_address']
            amount = trade_info['amount']
            side = trade_info['side']

            original_amount = trade_info.get('original_amount', amount)
            self.logger.info(f"Trade detectado de {trader_wallet[:8]}... - {side} {original_amount:.6f} SOL → {amount:.6f} SOL de {token_address}")

            # Validar trade con el motor
            is_valid, validation_checks = await self.validation_engine.validate_trade(
                trader_wallet=trader_wallet,
                token_address=token_address,
                amount_sol=amount,
                side=side
            )

            if not is_valid:
                # Obtener mensajes de error de los checks fallidos
                error_messages = []
                for check in validation_checks:
                    if check.result.value == 'failed':
                        error_messages.append(check.message)

                error_msg = '; '.join(error_messages) if error_messages else 'Validación fallida'

                self.logger.warning(
                    f"Trade no válido: {error_msg}",
                    extra={'trader': trader_wallet, 'token': token_address}
                )

                # Notificar trade no válido
                if self.notification_manager:
                    await self.notification_manager.notify_trade({
                        'side': side,
                        'token_address': token_address,
                        'token_name': trade_info.get('token_name', 'Token Desconocido'),
                        'token_symbol': trade_info.get('token_symbol', 'UNKN'),
                        'amount': amount,
                        'status': 'failed',
                        'error': error_msg
                    })
                return

            # Incrementar contador de trades válidos
            self.stats['trades_validated'] += 1

            # Crear y encolar posición
            position = Position(
                id=str(uuid.uuid4()),  # Generar ID único
                trader_wallet=trader_wallet,
                token_address=token_address,
                token_symbol=trade_info.get('token_symbol', token_address[:4].upper()),
                amount_sol=amount,
                amount_tokens=trade_info.get('token_amount', 0),  # Usar la cantidad de tokens del trade original
                side=PositionSide(side)  # Convertir string a enum
            )

            self.logger.info(f"Validando trade: {side} {amount:.6f} SOL de {token_address}")

            # Encolar posición (NO notificar aquí - se notificará cuando cambie de estado)
            await self.position_queue.add_position(position)
            self.logger.info(f"Trade añadido a la cola - ID: {position.id}")

            # NO notificar aquí - las notificaciones se harán cuando la posición cambie de estado

        except Exception as e:
            self.logger.error(f"Error procesando trade: {e}")

            # Notificar error
            if self.notification_manager:
                await self.notification_manager.notify_trade({
                    'side': trade_info.get('side', 'unknown') if 'trade_info' in locals() else 'unknown',
                    'token_address': trade_info.get('token_address', 'unknown') if 'trade_info' in locals() else 'unknown',
                    'token_name': trade_info.get('token_name', 'Token Desconocido') if 'trade_info' in locals() else 'Token Desconocido',
                    'token_symbol': trade_info.get('token_symbol', 'UNKN') if 'trade_info' in locals() else 'UNKN',
                    'amount': trade_info.get('amount', 0) if 'trade_info' in locals() else 0,
                    'status': 'failed',
                    'error': str(e)
                })

    def _validation_check_to_dict(self, check: Any) -> Dict[str, Any]:
        """Helper para convertir ValidationCheck a dict"""
        return {
            'name': check.name,
            'result': check.result.value,
            'message': check.message,
            'details': check.details,
            'timestamp': check.timestamp.isoformat()
        }

    async def _extract_trade_info(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extrae información relevante del mensaje de trade de PumpFun
        
        Args:
            data: Datos crudos del WebSocket
            
        Returns:
            Diccionario con información del trade o None
        """
        try:
            # Verificar que tengamos todos los campos necesarios
            if all(key in data for key in ['traderPublicKey', 'mint', 'solAmount', 'txType', 'signature']):
                return {
                    'trader': data['traderPublicKey'],
                    'token': data['mint'],
                    'token_symbol': '',  # PumpFun no envía símbolo
                    'action': 'buy' if data['txType'] == 'buy' else 'sell',
                    'amount': float(data['solAmount']),
                    'price': float(data.get('price', 0)),  # Podríamos calcular el precio si es necesario
                    'signature': data['signature'],
                    'timestamp': datetime.now().isoformat()
                }

            return None

        except Exception as e:
            self.logger.error(f"Error extrayendo información del trade: {str(e)}")
            return None

    async def _try_execute_trade(self, position: Position):
        """
        Intenta ejecutar un trade inmediatamente
        
        Args:
            position: Posición a ejecutar
        """
        try:
            if self.trade_executor:
                await self.trade_executor(position)
        except Exception as e:
            self.logger.error(
                f"Error ejecutando trade: {str(e)}",
                data={'position_id': position.id}
            )

    def _add_processed_signature(self, signature: str):
        """Añade una signature al cache de procesadas"""
        self.processed_signatures.add(signature)

        # Limitar tamaño del cache
        if len(self.processed_signatures) > self.signature_cache_size:
            # Eliminar las más antiguas (aproximación)
            excess = len(self.processed_signatures) - self.signature_cache_size
            for _ in range(excess):
                self.processed_signatures.pop()

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del callback"""
        return {
            **self.stats,
            'processed_signatures_count': len(self.processed_signatures),
            'active_traders': len(self.config.traders)
        }

    def reset_stats(self):
        """Resetea estadísticas"""
        self.stats = {
            'trades_received': 0,
            'trades_validated': 0,
            'trades_queued': 0,
            'trades_rejected': 0,
            'last_trade_time': None
        }

    def clear_processed_signatures(self):
        """Limpia el cache de signatures procesadas"""
        self.processed_signatures.clear()
        self.logger.debug("Cache de signatures procesadas limpiado")

    async def _get_token_info(self, token_address: str) -> Dict[str, str]:
        """
        Obtiene la información del token (nombre y símbolo)
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Diccionario con nombre y símbolo del token
        """
        try:
            # Intentar obtener metadatos del token
            metadata = await self.price_fetcher.get_token_metadata(token_address)
            if metadata:
                return {
                    'name': metadata.get('name', f"Token {token_address[:8]}..."),
                    'symbol': metadata.get('symbol', token_address[:4].upper())
                }

            # Si no se puede obtener, usar información básica
            return {
                'name': f"Token {token_address[:8]}...",
                'symbol': token_address[:4].upper()
            }

        except Exception as e:
            self.logger.warning(f"Error obteniendo información del token: {e}")
            return {
                'name': f"Token {token_address[:8]}...",
                'symbol': token_address[:4].upper()
            }
