# -*- coding: utf-8 -*-
"""
Gestor de cache inteligente para datos de trading
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from logging_system import AppLogger

from .models import TokenInfo, TraderStats, TraderTokenStats


class TradingDataStore:
    """Gestor de cache inteligente con TTL"""

    def __init__(self, token_cache_ttl: Optional[int] = None, trader_cache_ttl: Optional[int] = None):
        """
        Inicializa el gestor de cache inteligente.
        
        Args:
            token_cache_ttl: TTL para tokens en segundos (None = sin expiración)
            trader_cache_ttl: TTL para traders en segundos (None = sin expiración)
        """
        # Logger
        self._logger = AppLogger(self.__class__.__name__)

        # Cache de datos
        self._token_cache: Dict[str, TokenInfo] = {}
        self._trader_cache: Dict[str, TraderStats] = {}
        self._trader_token_cache: Dict[str, TraderTokenStats] = {}
        self._token_timestamps: Dict[str, datetime] = {}
        self._trader_timestamps: Dict[str, datetime] = {}
        self._trader_token_timestamps: Dict[str, datetime] = {}

        # Configuración de TTL (None = sin expiración)
        self.token_cache_ttl = token_cache_ttl
        self.trader_cache_ttl = trader_cache_ttl

        # Lock para operaciones concurrentes
        self._lock = asyncio.Lock()

        self._logger.debug(f"CacheManager inicializado - Token TTL: {token_cache_ttl}s, Trader TTL: {trader_cache_ttl}s")

    def get_token_data(self, token_address: str) -> Optional[TokenInfo]:
        """Obtiene datos de token del cache"""
        if self._is_token_valid(token_address):
            return self._token_cache.get(token_address)
        return None

    async def set_token_data(self, token_address: str, data: TokenInfo) -> None:
        """Establece datos de token en el cache"""
        async with self._lock:
            self._token_cache[token_address] = data
            self._token_timestamps[token_address] = datetime.now()
            self._logger.debug(f"Token cache actualizado: {token_address}")

    def get_trader_data(self, trader_wallet: str) -> Optional[TraderStats]:
        """Obtiene datos de trader del cache"""
        if self._is_trader_valid(trader_wallet):
            return self._trader_cache.get(trader_wallet)
        return None

    async def set_trader_data(self, trader_wallet: str, data: TraderStats) -> None:
        """Establece datos de trader en el cache"""
        async with self._lock:
            self._trader_cache[trader_wallet] = data
            self._trader_timestamps[trader_wallet] = datetime.now()
            self._logger.debug(f"Trader cache actualizado: {trader_wallet}")

    def get_trader_token_data(self, key: str) -> Optional[TraderTokenStats]:
        """Obtiene datos de trader-token del cache"""
        if self._is_trader_token_valid(key):
            return self._trader_token_cache.get(key)
        return None

    async def set_trader_token_data(self, key: str, data: TraderTokenStats) -> None:
        """Establece datos de trader-token en el cache"""
        async with self._lock:
            self._trader_token_cache[key] = data
            self._trader_token_timestamps[key] = datetime.now()
            self._logger.debug(f"Trader-token cache actualizado: {key}")

    def _is_token_valid(self, token_address: str) -> bool:
        """Verifica si el cache de token es válido"""
        if token_address not in self._token_timestamps:
            return False

        # Si TTL es None, el cache nunca expira
        if self.token_cache_ttl is None:
            return True

        timestamp = self._token_timestamps[token_address]
        return datetime.now() - timestamp < timedelta(seconds=self.token_cache_ttl)

    def _is_trader_valid(self, trader_wallet: str) -> bool:
        """Verifica si el cache de trader es válido"""
        if trader_wallet not in self._trader_timestamps:
            return False

        # Si TTL es None, el cache nunca expira
        if self.trader_cache_ttl is None:
            return True

        timestamp = self._trader_timestamps[trader_wallet]
        return datetime.now() - timestamp < timedelta(seconds=self.trader_cache_ttl)

    def _is_trader_token_valid(self, key: str) -> bool:
        """Verifica si el cache de trader-token es válido"""
        if key not in self._trader_token_timestamps:
            return False

        # Si TTL es None, el cache nunca expira
        if self.trader_cache_ttl is None:
            return True

        timestamp = self._trader_token_timestamps[key]
        return datetime.now() - timestamp < timedelta(seconds=self.trader_cache_ttl)

    def should_refresh_token(self, token_address: str) -> bool:
        """Determina si se debe refrescar el cache de token"""
        return not self._is_token_valid(token_address)

    def should_refresh_trader(self, trader_wallet: str) -> bool:
        """Determina si se debe refrescar el cache de trader"""
        return not self._is_trader_valid(trader_wallet)

    async def clear_token_cache(self, token_address: Optional[str] = None) -> None:
        """Limpia el cache de tokens"""
        async with self._lock:
            if token_address:
                self._token_cache.pop(token_address, None)
                self._token_timestamps.pop(token_address, None)
                self._logger.debug(f"Cache de token limpiado: {token_address}")
            else:
                self._token_cache.clear()
                self._token_timestamps.clear()
                self._logger.info("Cache de tokens limpiado completamente")

    async def clear_trader_cache(self, trader_wallet: Optional[str] = None) -> None:
        """Limpia el cache de traders"""
        async with self._lock:
            if trader_wallet:
                self._trader_cache.pop(trader_wallet, None)
                self._trader_timestamps.pop(trader_wallet, None)
                self._logger.debug(f"Cache de trader limpiado: {trader_wallet}")
            else:
                self._trader_cache.clear()
                self._trader_timestamps.clear()
                self._logger.info("Cache de traders limpiado completamente")

    async def clear_all_cache(self) -> None:
        """Limpia todo el cache"""
        async with self._lock:
            self._token_cache.clear()
            self._trader_cache.clear()
            self._token_timestamps.clear()
            self._trader_timestamps.clear()
            self._logger.info("Todo el cache limpiado")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del cache"""
        now = datetime.now()

        # Contar tokens expirados
        expired_tokens = 0
        if self.token_cache_ttl is not None:
            expired_tokens = sum(
                1 for timestamp in self._token_timestamps.values()
                if now - timestamp >= timedelta(seconds=self.token_cache_ttl)
            )

        # Contar traders expirados
        expired_traders = 0
        if self.trader_cache_ttl is not None:
            expired_traders = sum(
                1 for timestamp in self._trader_timestamps.values()
                if now - timestamp >= timedelta(seconds=self.trader_cache_ttl)
            )

        return {
            'token_cache_size': len(self._token_cache),
            'trader_cache_size': len(self._trader_cache),
            'expired_tokens': expired_tokens,
            'expired_traders': expired_traders,
            'token_cache_ttl': self.token_cache_ttl,
            'trader_cache_ttl': self.trader_cache_ttl
        }

    def set_token_ttl(self, ttl_seconds: Optional[int]) -> None:
        """
        Establece el TTL para tokens
        
        Args:
            ttl_seconds: TTL en segundos (None = sin expiración)
        """
        self.token_cache_ttl = ttl_seconds
        if ttl_seconds is None:
            self._logger.info("TTL de tokens deshabilitado (sin expiración)")
        else:
            self._logger.info(f"TTL de tokens actualizado a {ttl_seconds} segundos")

    def set_trader_ttl(self, ttl_seconds: Optional[int]) -> None:
        """
        Establece el TTL para traders
        
        Args:
            ttl_seconds: TTL en segundos (None = sin expiración)
        """
        self.trader_cache_ttl = ttl_seconds
        if ttl_seconds is None:
            self._logger.info("TTL de traders deshabilitado (sin expiración)")
        else:
            self._logger.info(f"TTL de traders actualizado a {ttl_seconds} segundos")

    def get_all_token_data(self) -> Dict[str, Any]:
        """Obtiene todos los datos de tokens del cache"""
        # Solo retornar datos válidos
        valid_tokens = {}
        for token_address, data in self._token_cache.items():
            if self._is_token_valid(token_address):
                valid_tokens[token_address] = data
        return valid_tokens

    def get_all_trader_data(self) -> Dict[str, Any]:
        """Obtiene todos los datos de traders del cache"""
        # Solo retornar datos válidos
        valid_traders = {}
        for trader_wallet, data in self._trader_cache.items():
            if self._is_trader_valid(trader_wallet):
                valid_traders[trader_wallet] = data
        return valid_traders

    def disable_token_cache_expiration(self) -> None:
        """Deshabilita la expiración del cache de tokens"""
        self.set_token_ttl(None)

    def disable_trader_cache_expiration(self) -> None:
        """Deshabilita la expiración del cache de traders"""
        self.set_trader_ttl(None)

    def disable_all_cache_expiration(self) -> None:
        """Deshabilita la expiración de todo el cache"""
        self.disable_token_cache_expiration()
        self.disable_trader_cache_expiration()

    def enable_token_cache_expiration(self, ttl_seconds: int = 300) -> None:
        """
        Habilita la expiración del cache de tokens
        
        Args:
            ttl_seconds: TTL en segundos (por defecto 5 minutos)
        """
        self.set_token_ttl(ttl_seconds)

    def enable_trader_cache_expiration(self, ttl_seconds: int = 600) -> None:
        """
        Habilita la expiración del cache de traders
        
        Args:
            ttl_seconds: TTL en segundos (por defecto 10 minutos)
        """
        self.set_trader_ttl(ttl_seconds)

    def enable_all_cache_expiration(self, token_ttl: int = 300, trader_ttl: int = 600) -> None:
        """
        Habilita la expiración de todo el cache
        
        Args:
            token_ttl: TTL para tokens en segundos (por defecto 5 minutos)
            trader_ttl: TTL para traders en segundos (por defecto 10 minutos)
        """
        self.enable_token_cache_expiration(token_ttl)
        self.enable_trader_cache_expiration(trader_ttl)
