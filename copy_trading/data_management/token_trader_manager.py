# -*- coding: utf-8 -*-
"""
TokenTraderManager Optimizado - Versión mejorada que delega completamente a data_management
"""
import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

from logging_system import AppLogger

from ..config import CopyTradingConfig
from .models import TokenInfo, TraderStats, TraderTokenStats
from .services import TraderStatsSyncService
from .fetch_data import TradingDataFetcher
from .cache_manager import CacheManager


class TokenTraderManager:
    """
    Gestor optimizado que delega completamente a los componentes de data_management.
    No mantiene estado propio, solo coordina entre componentes optimizados.
    """

    def __init__(self, config: CopyTradingConfig, trading_data_fetcher: Optional[TradingDataFetcher] = None, 
                    token_cache_ttl: Optional[int] = 300, trader_cache_ttl: Optional[int] = 600):
        """
        Inicializa el gestor que delega a data_management.
        
        Args:
            config: Configuración del sistema
            trading_data_fetcher: Cliente para obtener datos de trading (opcional)
            token_cache_ttl: TTL para tokens en segundos (None = sin expiración)
            trader_cache_ttl: TTL para traders en segundos (None = sin expiración)
        """
        try:
            self.config = config

            self._logger = AppLogger(self.__class__.__name__)

            # Componentes optimizados de data_management
            self.trading_data_fetcher = trading_data_fetcher or TradingDataFetcher()
            self.cache_manager = CacheManager(token_cache_ttl, trader_cache_ttl)

            # Solo un lock para coordinación (no para estado)
            self._lock = asyncio.Lock()

            self._logger.debug("TokenTraderManager inicializado")
        except Exception as e:
            print(f"Error inicializando TokenTraderManager: {e}")
            raise

    # ==================== MÉTODOS PARA TOKENS ====================

    async def fetch_token_info(self, token_address: str, lock_acquired: bool = False) -> Optional[TokenInfo]:
        """
        Obtiene la información de un token delegando al cache optimizado.
        """
        if not lock_acquired:
            async with self._lock:
                return await self._fetch_token_info(token_address)
        else:
            return await self._fetch_token_info(token_address)

    async def get_token_info(self, token_address: str, force_refresh: bool = False) -> Optional[TokenInfo]:
        """
        Obtiene la información de un token delegando al cache optimizado.
        
        Args:
            token_address: Dirección del token
            force_refresh: Forzar actualización desde la fuente
            
        Returns:
            TokenInfo del token
        """
        try:
            # Siempre intentar cache primero (excepto si force_refresh)
            if not force_refresh:
                cached_data = await self.cache_manager.get_token_data(token_address)
                if cached_data:
                    # Verificar si el token del cache tiene información completa y válida
                    has_invalid_name = not cached_data.name or cached_data.name.strip() in ('Unknown', '')
                    has_invalid_symbol = not cached_data.symbol or cached_data.symbol.strip() in ('UNK', '')

                    if has_invalid_name or has_invalid_symbol:
                        self._logger.debug(f"Token {token_address} tiene información incompleta, forzando refresh")
                        # Si la información está incompleta o es genérica, forzar refresh
                        force_refresh = True
                    else:
                        self._logger.debug(f"Token {token_address} obtenido del cache")
                        return cached_data

            # Si no hay cache o force_refresh, obtener datos frescos
            async with self._lock:
                self._logger.debug(f"Obteniendo información fresca para token {token_address}")
                token_info = await self._fetch_token_info(token_address)

                # Guardar en cache optimizado solo si se obtuvo información válida
                if token_info:
                    await self.cache_manager.set_token_data(token_address, token_info)
                    self._logger.debug(f"Token {token_address} guardado en cache")
                    return token_info
                else:
                    # Si no se pudo obtener información fresca, intentar retornar del cache
                    cached_data = await self.cache_manager.get_token_data(token_address)
                    if cached_data:
                        self._logger.debug(f"Retornando datos del cache para {token_address}")
                        return cached_data

                    self._logger.warning(f"No se pudo obtener información del token {token_address}")
                    return None
        except Exception as e:
            self._logger.error(f"Error obteniendo información del token {token_address}: {e}")
            return None

    async def add_token_info(self, token_address: str, name: str, symbol: str) -> TokenInfo:
        """
        Actualiza la información de un token.
        
        Args:
            token_address: Dirección del token
            name: Nombre del token
            symbol: Símbolo del token
            
        Returns:
            TokenInfo actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_info = await self.cache_manager.get_token_data(token_address) or TokenInfo()

            # Actualizar atributos preservando traders existentes
            current_info.name = name
            current_info.symbol = symbol
            current_info.num_traders = len(current_info.traders)

            # Guardar en cache optimizado
            await self.cache_manager.set_token_data(token_address, current_info)

            self._logger.debug(f"Token {token_address} actualizado: {name} {symbol}")
            return current_info

    async def add_trader_to_token(self, token_address: str, trader_wallet: str) -> TokenInfo:
        """
        Agrega un trader a la lista de traders de un token.
        
        Args:
            token_address: Dirección del token
            trader_wallet: Wallet del trader
            
        Returns:
            TokenInfo actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_info = await self.cache_manager.get_token_data(token_address) or TokenInfo()

            # Actualizar atributos preservando nombre y símbolo
            current_info.add_trader(trader_wallet)
            current_info.num_traders = len(current_info.traders)

            # Guardar en cache optimizado
            await self.cache_manager.set_token_data(token_address, current_info)

            self._logger.debug(f"Trader {trader_wallet} añadido a token {token_address}")
            return current_info

    async def remove_trader_from_token(self, token_address: str, trader_wallet: str) -> TokenInfo:
        """
        Remueve un trader de la lista de traders de un token.
        
        Args:
            token_address: Dirección del token
            trader_wallet: Wallet del trader
            
        Returns:
            TokenInfo actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_info = await self.cache_manager.get_token_data(token_address)

            if current_info and trader_wallet in current_info.traders:
                current_info.remove_trader(trader_wallet)
                current_info.num_traders = len(current_info.traders)

                # Guardar en cache optimizado
                await self.cache_manager.set_token_data(token_address, current_info)

                self._logger.debug(f"Trader {trader_wallet} removido de token {token_address}")

            return current_info or TokenInfo()

    async def get_all_tokens(self) -> Dict[str, TokenInfo]:
        """
        Obtiene todos los tokens del cache optimizado.
        
        Returns:
            Diccionario con todos los tokens
        """
        # Delegar completamente al cache manager
        return await self.cache_manager.get_all_token_data()

    async def get_tokens_by_trader(self, trader_wallet: str) -> Set[str]:
        """
        Obtiene todos los tokens que tiene un trader.
        
        Args:
            trader_wallet: Wallet del trader
            
        Returns:
            Lista de direcciones de tokens
        """
        # Obtener todos los tokens del cache
        all_tokens = await self.get_all_tokens()

        tokens = set()
        for token_address, token_info in all_tokens.items():
            if trader_wallet in token_info.traders:
                tokens.add(token_address)
        return tokens

    # ==================== MÉTODOS PARA TRADER TOKEN STATS ====================

    async def get_trader_token_stats(self, trader_wallet: str, token_address: str) -> TraderTokenStats:
        """
        Obtiene las estadísticas de un trader para un token específico.
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            
        Returns:
            TraderTokenStats del trader para el token
        """
        # Generar clave única para la combinación trader-token
        key = f"{trader_wallet}_{token_address}"

        # Intentar obtener del cache
        cached_data = await self.cache_manager.get_trader_token_data(key)
        if cached_data:
            return cached_data

        # Si no existe, crear uno nuevo
        token_info = await self.get_token_info(token_address)
        # Verificar que el símbolo no esté vacío
        token_symbol = token_info.symbol if token_info and token_info.symbol else "UNK"

        trader_token_stats = TraderTokenStats(
            trader_wallet=trader_wallet,
            token_address=token_address,
            token_symbol=token_symbol
        )

        # Guardar en cache
        await self.cache_manager.set_trader_token_data(key, trader_token_stats)
        return trader_token_stats

    async def _get_trader_token_stats_internal(self, trader_wallet: str, token_address: str) -> TraderTokenStats:
        """
        Método interno para obtener TraderTokenStats sin adquirir el lock principal.
        Usado por los métodos register_trader_token_* para evitar deadlocks.
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            
        Returns:
            TraderTokenStats del trader para el token
        """
        # Generar clave única para la combinación trader-token
        key = f"{trader_wallet}_{token_address}"

        # Intentar obtener del cache
        cached_data = await self.cache_manager.get_trader_token_data(key)
        if cached_data:
            return cached_data

        # Si no existe, crear uno nuevo
        token_info = await self.get_token_info(token_address)
        # Verificar que el símbolo no esté vacío
        token_symbol = token_info.symbol if token_info and token_info.symbol else "UNK"

        trader_token_stats = TraderTokenStats(
            trader_wallet=trader_wallet,
            token_address=token_address,
            token_symbol=token_symbol
        )

        # Guardar en cache
        await self.cache_manager.set_trader_token_data(key, trader_token_stats)
        return trader_token_stats

    async def register_trader_token_open_position(self, trader_wallet: str, token_address: str, volume_sol: str, timestamp: Optional[str] = None) -> TraderTokenStats:
        """
        Registra una posición abierta para un trader en un token específico.
        Actualiza simultáneamente TraderStats y TraderTokenStats
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            volume_sol: Volumen en SOL
            timestamp: Timestamp del trade (opcional)
            
        Returns:
            TraderTokenStats actualizado
        """
        # Obtener o crear TraderTokenStats sin el lock principal
        trader_token_stats = await self._get_trader_token_stats_internal(trader_wallet, token_address)

        # Obtener TraderStats actual
        trader_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

        # Preservar el nombre del trader si no está establecido
        if not trader_stats.nickname:
            trader_info = self.config.get_trader_info(trader_wallet)
            if trader_info and trader_info.nickname:
                trader_stats.nickname = trader_info.nickname

        # Actualizar ambos modelos simultáneamente
        updated_trader_stats, updated_trader_token_stats = TraderStatsSyncService.sync_models(
            trader_stats=trader_stats,
            trader_token_stats=trader_token_stats,
            operation='open_position', 
            sync_operation={
                'volume_sol_open': volume_sol,
                'timestamp': timestamp
            }
        )

        # Guardar ambos en cache
        key = f"{trader_wallet}_{token_address}"
        await self.cache_manager.set_trader_token_data(key, updated_trader_token_stats)
        await self.cache_manager.set_trader_data(trader_wallet, updated_trader_stats)

        self._logger.debug(f"Posición abierta registrada para {trader_wallet} en {token_address}: {volume_sol}")
        return updated_trader_token_stats

    async def register_trader_token_closed_position(self, trader_wallet: str, token_address: str, volume_sol: str, timestamp: Optional[str] = None) -> TraderTokenStats:
        """
        Registra una posición cerrada para un trader en un token específico.
        Actualiza simultáneamente TraderStats y TraderTokenStats
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            volume_sol: Volumen en SOL
            timestamp: Timestamp del trade (opcional)
            
        Returns:
            TraderTokenStats actualizado
        """
        # Obtener o crear TraderTokenStats sin el lock principal
        trader_token_stats = await self._get_trader_token_stats_internal(trader_wallet, token_address)

        # Obtener TraderStats actual
        trader_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

        # Preservar el nombre del trader si no está establecido
        if not trader_stats.nickname:
            trader_info = self.config.get_trader_info(trader_wallet)
            if trader_info and trader_info.nickname:
                trader_stats.nickname = trader_info.nickname

        # Actualizar ambos modelos simultáneamente
        updated_trader_stats, updated_trader_token_stats = TraderStatsSyncService.sync_models(
            trader_stats=trader_stats,
            trader_token_stats=trader_token_stats,
            operation='closed_position', 
            sync_operation={
                'volume_sol_closed': volume_sol,
                'timestamp': timestamp
            }
        )

        # Guardar ambos en cache
        key = f"{trader_wallet}_{token_address}"
        await self.cache_manager.set_trader_token_data(key, updated_trader_token_stats)
        await self.cache_manager.set_trader_data(trader_wallet, updated_trader_stats)

        self._logger.debug(f"Posición cerrada registrada para {trader_wallet} en {token_address}: {volume_sol}")
        return updated_trader_token_stats

    async def register_trader_token_pnl(self, trader_wallet: str, token_address: str, pnl_sol: str, pnl_sol_with_costs: str) -> TraderTokenStats:
        """
        Registra P&L para un trader en un token específico.
        Actualiza simultáneamente TraderStats y TraderTokenStats sin iteraciones innecesarias.
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            pnl_sol: P&L en SOL
            pnl_sol_with_costs: P&L en SOL con costos
            
        Returns:
            TraderTokenStats actualizado
        """
        # Obtener o crear TraderTokenStats sin el lock principal
        trader_token_stats = await self._get_trader_token_stats_internal(trader_wallet, token_address)

        # Obtener TraderStats actual
        trader_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

        # Preservar el nombre del trader si no está establecido
        if not trader_stats.nickname:
            trader_info = self.config.get_trader_info(trader_wallet)
            if trader_info and trader_info.nickname:
                trader_stats.nickname = trader_info.nickname

        # Actualizar ambos modelos simultáneamente
        updated_trader_stats, updated_trader_token_stats = TraderStatsSyncService.sync_models(
            trader_stats=trader_stats,
            trader_token_stats=trader_token_stats,
            operation='pnl', 
            sync_operation={
                'pnl_sol': pnl_sol,
                'pnl_sol_with_costs': pnl_sol_with_costs,
            }
        )

        # Guardar ambos en cache
        key = f"{trader_wallet}_{token_address}"
        await self.cache_manager.set_trader_token_data(key, updated_trader_token_stats)
        await self.cache_manager.set_trader_data(trader_wallet, updated_trader_stats)

        self._logger.debug(f"P&L registrado para {trader_wallet} en {token_address}: {pnl_sol}")
        return updated_trader_token_stats

    async def get_all_trader_token_stats(self, trader_wallet: str) -> List[TraderTokenStats]:
        """
        Obtiene todas las estadísticas de un trader por token.
        
        Args:
            trader_wallet: Wallet del trader
            
        Returns:
            Lista de TraderTokenStats del trader
        """
        # Obtener todos los tokens del trader
        token_addresses = await self.get_tokens_by_trader(trader_wallet)

        trader_token_stats_list = []
        for token_address in token_addresses:
            key = f"{trader_wallet}_{token_address}"
            stats = await self.cache_manager.get_trader_token_data(key)
            if stats:
                trader_token_stats_list.append(stats)

        return trader_token_stats_list

    async def _sync_trader_stats_from_token_stats(self, trader_wallet: str) -> None:
        """
        Sincroniza TraderStats desde TraderTokenStats.
        
        Args:
            trader_wallet: Wallet del trader a sincronizar
        """
        # Obtener todas las estadísticas del trader por token
        trader_token_stats_list = await self.get_all_trader_token_stats(trader_wallet)

        if trader_token_stats_list:
            # Crear TraderStats agregado
            trader_info = self.config.get_trader_info(trader_wallet)
            trader_name = trader_info.nickname if trader_info else "UNKNOWN"

            aggregated_stats = TraderStatsSyncService.aggregate_trader_stats_from_token_stats(
                trader_token_stats_list, trader_name
            )

            # Guardar en cache
            await self.cache_manager.set_trader_data(trader_wallet, aggregated_stats)

            self._logger.debug(f"TraderStats sincronizado para {trader_wallet} desde {len(trader_token_stats_list)} tokens")

    # ==================== MÉTODOS PARA TRADERS ====================

    async def initialize_system_trader_stats(self) -> None:
        """
        Inicializa las estadísticas de los traders del sistema.
        """
        async with self._lock:
            for trader_info in self.config.traders:
                await self._fetch_trader_stats(trader_info.wallet_address)

    async def get_trader_stats(self, trader_wallet: str, force_refresh: bool = False) -> TraderStats:
        """
        Obtiene la información de un trader delegando al cache optimizado.
        
        Args:
            trader_wallet: Wallet del trader
            force_refresh: Forzar actualización desde la fuente
            
        Returns:
            TraderStats del trader
        """
        try:
            # Siempre intentar cache primero (excepto si force_refresh)
            if not force_refresh:
                cached_data = await self.cache_manager.get_trader_data(trader_wallet)
                if cached_data:
                    self._logger.debug(f"Trader {trader_wallet} obtenido del cache")
                    return cached_data

            # Si no hay cache o force_refresh, obtener datos frescos
            async with self._lock:
                self._logger.debug(f"Obteniendo datos frescos para trader {trader_wallet}")
                trader_stats = await self._fetch_trader_stats(trader_wallet)

                # Guardar en cache optimizado solo si se obtuvo información válida
                if trader_stats:
                    await self.cache_manager.set_trader_data(trader_wallet, trader_stats)
                    self._logger.debug(f"Trader {trader_wallet} guardado en cache")
                    return trader_stats
                else:
                    # Si no se pudo obtener información fresca, intentar retornar del cache
                    cached_data = await self.cache_manager.get_trader_data(trader_wallet)
                    if cached_data:
                        self._logger.debug(f"Retornando datos del cache para {trader_wallet}")
                        return cached_data

                    self._logger.warning(f"No se pudo obtener información del trader {trader_wallet}")
                    return TraderStats()
        except Exception as e:
            self._logger.error(f"Error obteniendo información del trader {trader_wallet}: {e}")
            return TraderStats()

    async def update_trader_stats(self, trader_wallet: str, **kwargs) -> TraderStats:
        """
        Actualiza las estadísticas de un trader.
        
        Args:
            trader_wallet: Wallet del trader
            **kwargs: Atributos a actualizar
            
        Returns:
            TraderStats actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

            # Preservar el nombre del trader si no está establecido
            if not current_stats.nickname:
                trader_info = self.config.get_trader_info(trader_wallet)
                if trader_info and trader_info.nickname:
                    current_stats.nickname = trader_info.nickname

            # Actualizar atributos
            for key, value in kwargs.items():
                if hasattr(current_stats, key):
                    setattr(current_stats, key, value)

            # Guardar en cache optimizado
            await self.cache_manager.set_trader_data(trader_wallet, current_stats)

            self._logger.debug(f"Trader {trader_wallet} actualizado")
            return current_stats

    async def register_open_position(self, trader_wallet: str, volume_sol: str) -> TraderStats:
        """
        Incrementa estadísticas de un trader al abrir una posición.
        
        Args:
            trader_wallet: Wallet del trader
            volume_sol: Volumen en SOL
            
        Returns:
            TraderStats actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

            # Preservar el nombre del trader si no está establecido
            if not current_stats.nickname:
                trader_info = self.config.get_trader_info(trader_wallet)
                if trader_info and trader_info.nickname:
                    current_stats.nickname = trader_info.nickname

            # Aplicar incrementos
            current_stats.register_open_position(volume_sol)

            # Guardar en cache optimizado
            await self.cache_manager.set_trader_data(trader_wallet, current_stats)

            self._logger.debug(f"Posición abierta registrada para {trader_wallet}: {volume_sol}")
            return current_stats

    async def register_closed_position(self, trader_wallet: str, volume_sol: str) -> TraderStats:
        """
        Incrementa estadísticas de un trader al cerrar una posición.
        
        Args:
            trader_wallet: Wallet del trader
            volume_sol: Volumen en SOL
            
        Returns:
            TraderStats actualizado
        """
        async with self._lock:
            # Obtener datos actuales del cache
            current_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

            # Preservar el nombre del trader si no está establecido
            if not current_stats.nickname:
                trader_info = self.config.get_trader_info(trader_wallet)
                if trader_info and trader_info.nickname:
                    current_stats.nickname = trader_info.nickname

            # Aplicar incrementos
            current_stats.register_closed_position(volume_sol)

            # Guardar en cache optimizado
            await self.cache_manager.set_trader_data(trader_wallet, current_stats)

            self._logger.debug(f"Posición cerrada registrada para {trader_wallet}: {volume_sol}")
            return current_stats

    async def register_pnl(self, trader_wallet: str, pnl_sol: str, pnl_sol_with_costs: str) -> TraderStats:
        """
        Incrementa estadísticas de un trader al registrar un P&L.
        
        Args:
            trader_wallet: Wallet del trader
            pnl_sol: P&L en SOL
            pnl_sol_with_costs: P&L en SOL con costos
            
        Returns:
            TraderStats actualizado
        """
        try:
            async with self._lock:
                # Obtener datos actuales del cache
                current_stats = await self.cache_manager.get_trader_data(trader_wallet) or TraderStats()

                # Preservar el nombre del trader si no está establecido
                if not current_stats.nickname:
                    trader_info = self.config.get_trader_info(trader_wallet)
                    if trader_info and trader_info.nickname:
                        current_stats.nickname = trader_info.nickname

                # Aplicar incrementos
                current_stats.register_pnl(pnl_sol, pnl_sol_with_costs)

                # Guardar en cache optimizado
                await self.cache_manager.set_trader_data(trader_wallet, current_stats)

                self._logger.debug(f"P&L registrado para {trader_wallet}: {pnl_sol}")
                return current_stats
        except Exception as e:
            self._logger.error(f"Error registrando P&L para {trader_wallet}: {e}")
            return TraderStats()

    async def get_all_traders(self) -> Dict[str, TraderStats]:
        """
        Obtiene todos los traders del cache optimizado.
        
        Returns:
            Diccionario con todos los traders
        """
        # Delegar completamente al cache manager
        return await self.cache_manager.get_all_trader_data()

    async def get_top_traders(self, limit: int = 10, sort_by: str = 'total_volume_sol') -> List[tuple]:
        """
        Obtiene los mejores traders ordenados por un criterio.
        
        Args:
            limit: Número máximo de traders a retornar
            sort_by: Campo por el cual ordenar
            
        Returns:
            Lista de tuplas (trader_wallet, TraderStats) ordenadas
        """
        # Obtener todos los traders del cache
        all_traders = await self.get_all_traders()
        traders = list(all_traders.items())

        # Ordenar por el campo especificado
        if sort_by in ['total_volume_sol', 'total_pnl_sol', 'total_pnl_sol_with_fees']:
            # Ordenar por valores monetarios (strings)
            traders.sort(
                key=lambda x: float(getattr(x[1], sort_by) or '0'),
                reverse=True
            )
        elif sort_by in ['open_positions', 'closed_positions', 'total_trades']:
            # Ordenar por contadores enteros
            traders.sort(
                key=lambda x: getattr(x[1], sort_by) or 0,
                reverse=True
            )
        else:
            # Fallback: ordenar por wallet
            traders.sort(key=lambda x: x[0])

        return traders[:limit]

    # ==================== MÉTODOS PRIVADOS ====================

    async def _fetch_token_info(self, token_address: str) -> Optional[TokenInfo]:
        """Obtiene información del token desde la fuente externa."""
        try:
            # Obtener información existente del cache primero
            existing_info = await self.cache_manager.get_token_data(token_address)

            # Intentar obtener datos frescos de la fuente externa
            token_data = await self.trading_data_fetcher.get_token_trading_info(token_address)

            if token_data:
                # Preservar traders existentes
                existing_traders = existing_info.traders if existing_info else set()

                # Usar datos frescos para nombre y símbolo, pero preservar traders existentes
                # Verificar que los valores no estén vacíos y no sean genéricos
                fresh_name = token_data.get('name', '').strip()
                fresh_symbol = token_data.get('symbol', '').strip()

                # Considerar valores genéricos como inválidos
                is_fresh_name_valid = fresh_name and fresh_name not in ('Unknown', '')
                is_fresh_symbol_valid = fresh_symbol and fresh_symbol not in ('UNK', '')

                # Usar valores existentes si están disponibles y son válidos
                existing_name_valid = (existing_info and 
                                        existing_info.name and 
                                        existing_info.name.strip() not in ('Unknown', ''))
                existing_symbol_valid = (existing_info and 
                                        existing_info.symbol and 
                                        existing_info.symbol.strip() not in ('UNK', ''))

                # Priorizar datos frescos válidos, luego existentes válidos, finalmente fallbacks
                if is_fresh_name_valid:
                    final_name = fresh_name
                elif existing_name_valid and existing_info:
                    final_name = existing_info.name
                else:
                    final_name = 'Unknown'

                if is_fresh_symbol_valid:
                    final_symbol = fresh_symbol
                elif existing_symbol_valid and existing_info:
                    final_symbol = existing_info.symbol
                else:
                    final_symbol = 'UNK'

                token_info = TokenInfo(
                    name=final_name,
                    symbol=final_symbol,
                    num_traders=len(existing_traders),
                    traders=existing_traders.copy()
                )

                self._logger.debug(f"Información del token {token_address} actualizada desde fuente externa")
                return token_info
            else:
                # Si no se pueden obtener datos frescos, retornar la información existente
                if existing_info:
                    self._logger.debug(f"Retornando información existente del cache para {token_address}")
                    return existing_info
                else:
                    self._logger.warning(f"No se pudo obtener información del token {token_address}")
                    return None

        except Exception as e:
            self._logger.error(f"Error al obtener información del token {token_address}: {e}")

            # En caso de error, retornar la información existente del cache
            existing_info = await self.cache_manager.get_token_data(token_address)
            if existing_info:
                self._logger.debug(f"Retornando información existente del cache tras error para {token_address}")
                return existing_info

            return None

    async def _fetch_trader_stats(self, trader_wallet: str) -> TraderStats:
        """Obtiene información del trader desde la fuente externa."""
        trader_info = self.config.get_trader_info(trader_wallet)
        if not trader_info:
            self._logger.warning(f"Trader {trader_wallet} no encontrado en la configuración")
            return TraderStats()

        try:
            # Obtener datos existentes del cache si los hay
            existing_stats = await self.cache_manager.get_trader_data(trader_wallet)
            if existing_stats:
                # Preservar el nombre del trader_info si no está en los datos existentes
                if not existing_stats.nickname and trader_info.nickname:
                    existing_stats.nickname = trader_info.nickname
                trader_stats = existing_stats
            else:
                trader_stats = TraderStats(nickname=trader_info.nickname)

            self._logger.debug(f"Información del trader {trader_wallet} actualizada")
            return trader_stats

        except Exception as e:
            self._logger.error(f"Error al obtener información del trader {trader_wallet}: {e}")
            return TraderStats()

    # ==================== MÉTODOS DE UTILIDAD ====================

    async def clear_cache(self) -> None:
        """Limpia todo el cache optimizado."""
        try:
            await self.cache_manager.clear_all_cache()
            self._logger.info("Cache limpiado completamente")
        except Exception as e:
            self._logger.error(f"Error limpiando cache: {e}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del cache optimizado."""
        return await self.cache_manager.get_cache_stats()

    async def export_data(self) -> Dict[str, Any]:
        """Exporta todos los datos del cache optimizado."""
        all_tokens = await self.get_all_tokens()
        all_traders = await self.get_all_traders()

        return {
            'tokens': {
                addr: token_info.to_dict() 
                for addr, token_info in all_tokens.items()
            },
            'traders': {
                wallet: trader_stats.to_dict() 
                for wallet, trader_stats in all_traders.items()
            },
            'exported_at': datetime.now().isoformat()
        }

    async def import_data(self, data: Dict[str, Any]) -> None:
        """Importa datos al cache optimizado."""
        try:
            # Importar tokens
            for addr, token_data in data.get('tokens', {}).items():
                token_info = TokenInfo.from_dict(token_data)
                await self.cache_manager.set_token_data(addr, token_info)

            # Importar traders
            for wallet, trader_data in data.get('traders', {}).items():
                trader_stats = TraderStats.from_dict(trader_data)
                await self.cache_manager.set_trader_data(wallet, trader_stats)

            self._logger.info(f"Datos importados: {len(data.get('tokens', {}))} tokens, {len(data.get('traders', {}))} traders")
        except Exception as e:
            self._logger.error(f"Error importando datos: {e}")

    async def close(self) -> None:
        """Cierra el manager y libera recursos."""
        try:
            if self.trading_data_fetcher:
                await self.trading_data_fetcher.close()
            self._logger.debug("TokenTraderManager cerrado")
        except Exception as e:
            self._logger.error(f"Error cerrando TokenTraderManager: {e}")

    # ==================== MÉTODOS DE CONFIGURACIÓN DE CACHE ====================

    def disable_token_cache_expiration(self) -> None:
        """Deshabilita la expiración del cache de tokens"""
        self.cache_manager.disable_token_cache_expiration()

    def disable_trader_cache_expiration(self) -> None:
        """Deshabilita la expiración del cache de traders"""
        self.cache_manager.disable_trader_cache_expiration()

    def disable_all_cache_expiration(self) -> None:
        """Deshabilita la expiración de todo el cache"""
        self.cache_manager.disable_all_cache_expiration()

    def enable_token_cache_expiration(self, ttl_seconds: int = 300) -> None:
        """
        Habilita la expiración del cache de tokens
        
        Args:
            ttl_seconds: TTL en segundos (por defecto 5 minutos)
        """
        self.cache_manager.enable_token_cache_expiration(ttl_seconds)

    def enable_trader_cache_expiration(self, ttl_seconds: int = 600) -> None:
        """
        Habilita la expiración del cache de traders
        
        Args:
            ttl_seconds: TTL en segundos (por defecto 10 minutos)
        """
        self.cache_manager.enable_trader_cache_expiration(ttl_seconds)

    def enable_all_cache_expiration(self, token_ttl: int = 300, trader_ttl: int = 600) -> None:
        """
        Habilita la expiración de todo el cache
        
        Args:
            token_ttl: TTL para tokens en segundos (por defecto 5 minutos)
            trader_ttl: TTL para traders en segundos (por defecto 10 minutos)
        """
        self.cache_manager.enable_all_cache_expiration(token_ttl, trader_ttl)

    def set_token_cache_ttl(self, ttl_seconds: Optional[int]) -> None:
        """
        Establece el TTL para tokens
        
        Args:
            ttl_seconds: TTL en segundos (None = sin expiración)
        """
        self.cache_manager.set_token_ttl(ttl_seconds)

    def set_trader_cache_ttl(self, ttl_seconds: Optional[int]) -> None:
        """
        Establece el TTL para traders
        
        Args:
            ttl_seconds: TTL en segundos (None = sin expiración)
        """
        self.cache_manager.set_trader_ttl(ttl_seconds)
