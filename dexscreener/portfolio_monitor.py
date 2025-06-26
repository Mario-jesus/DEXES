# -*- coding: utf-8 -*-
"""
DexScreener Portfolio Monitor - Monitoreo de portfolio de tokens
Integrado con SolanaWalletManager para tracking de posiciones
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import json

from solana_manager.wallet_manager import SolanaWalletManager
from solana_manager.account_info import SolanaAccountInfo
from .price_tracker import DexScreenerPriceTracker, TokenPrice


@dataclass
class TokenPosition:
    """Posición de un token en el portfolio"""
    token_address: str
    symbol: str
    name: str
    balance: float
    current_price_usd: float
    current_value_usd: float
    entry_price_usd: Optional[float] = None
    entry_value_usd: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_percentage: Optional[float] = None
    last_updated: datetime = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'token_address': self.token_address,
            'symbol': self.symbol,
            'name': self.name,
            'balance': self.balance,
            'current_price_usd': self.current_price_usd,
            'current_value_usd': self.current_value_usd,
            'entry_price_usd': self.entry_price_usd,
            'entry_value_usd': self.entry_value_usd,
            'pnl_usd': self.pnl_usd,
            'pnl_percentage': self.pnl_percentage,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }


@dataclass
class PortfolioSnapshot:
    """Snapshot del portfolio completo"""
    total_value_usd: float
    sol_balance: float
    sol_value_usd: float
    token_positions: List[TokenPosition]
    total_pnl_usd: float
    total_pnl_percentage: float
    snapshot_time: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_value_usd': self.total_value_usd,
            'sol_balance': self.sol_balance,
            'sol_value_usd': self.sol_value_usd,
            'token_positions': [pos.to_dict() for pos in self.token_positions],
            'total_pnl_usd': self.total_pnl_usd,
            'total_pnl_percentage': self.total_pnl_percentage,
            'snapshot_time': self.snapshot_time.isoformat()
        }


class DexScreenerPortfolioMonitor:
    """
    Monitor de portfolio usando DexScreener para precios
    Integrado con SolanaWalletManager para obtener balances reales
    """
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        """
        Inicializa el monitor de portfolio
        
        Args:
            wallet_manager: Instancia configurada de SolanaWalletManager
        """
        if not wallet_manager.is_wallet_loaded():
            raise ValueError("❌ Wallet no cargada. Usa wallet_manager.load_wallet() primero")
        
        self.wallet_manager = wallet_manager
        self.account_info = SolanaAccountInfo(wallet_manager)
        self.price_tracker = DexScreenerPriceTracker(wallet_manager)
        
        # Configuración
        self.wallet_address = wallet_manager.get_address()
        self.portfolio_history = []
        self.position_entries = {}  # {token_address: {'price': float, 'value': float, 'timestamp': datetime}}
        
        # Archivo para persistir datos
        self.portfolio_file = f"portfolio_{self.wallet_address[:8]}.json"
        
        print("📊 DexScreener Portfolio Monitor inicializado")
        print(f"📍 Wallet: {self.wallet_address[:8]}...{self.wallet_address[-8:]}")
        
        # Cargar datos históricos si existen
        self._load_portfolio_data()

    def get_detailed_balance(self) -> Dict[str, Any]:
        """
        Obtiene balance detallado mostrando SOL y todos los tokens con sus valores
        
        Returns:
            Dict con información completa de balances
        """
        try:
            print(f"💰 BALANCE DETALLADO DE WALLET")
            print("=" * 60)
            
            # Balance SOL
            sol_balance_info = self.account_info.get_balance_info(self.wallet_address)
            sol_balance = sol_balance_info['sol_balance']
            sol_price_usd = sol_balance_info['sol_price_usd']
            sol_value_usd = sol_balance_info['usd_value']
            
            print(f"🪙 SOL:")
            print(f"   Balance: {sol_balance:.6f} SOL")
            print(f"   Precio: ${sol_price_usd:.2f} USD")
            print(f"   Valor: ${sol_value_usd:.2f} USD")
            print()
            
            # Tokens
            token_accounts = self.account_info.get_token_accounts(self.wallet_address)
            total_tokens_value_usd = 0
            token_details = []
            
            print(f"🪙 TOKENS ({len(token_accounts)} encontrados):")
            
            for i, token_account in enumerate(token_accounts, 1):
                try:
                    token_address = token_account['mint']
                    balance = float(token_account['balance'])
                    decimals = token_account['decimals']
                    
                    print(f"\n   {i}. Token: {token_address}")
                    print(f"      Balance: {balance:,.{min(decimals, 6)}f} tokens")
                    print(f"      Decimales: {decimals}")
                    
                    if balance > 0:
                        # Obtener precio
                        token_price = self.price_tracker.get_token_price(token_address)
                        
                        if token_price and token_price.price_usd > 0:
                            value_usd = balance * token_price.price_usd
                            value_sol = value_usd / sol_price_usd if sol_price_usd > 0 else 0
                            
                            total_tokens_value_usd += value_usd
                            
                            token_detail = {
                                'address': token_address,
                                'symbol': token_price.symbol or f"TOKEN_{token_address[:8]}",
                                'name': token_price.name or "Unknown Token",
                                'balance': balance,
                                'decimals': decimals,
                                'price_usd': token_price.price_usd,
                                'value_usd': value_usd,
                                'value_sol': value_sol
                            }
                            token_details.append(token_detail)
                            
                            print(f"      Nombre: {token_price.name}")
                            print(f"      Símbolo: {token_price.symbol}")
                            print(f"      Precio: ${token_price.price_usd:.10f} USD")
                            print(f"      Valor USD: ${value_usd:.6f}")
                            print(f"      Valor SOL: {value_sol:.6f} SOL")
                        else:
                            print(f"      ⚠️ No se pudo obtener precio")
                    else:
                        print(f"      ⚠️ Balance: 0")
                        
                except Exception as e:
                    print(f"      ❌ Error: {e}")
            
            # Resumen total
            total_value_usd = sol_value_usd + total_tokens_value_usd
            total_value_sol = sol_balance + (total_tokens_value_usd / sol_price_usd if sol_price_usd > 0 else 0)
            
            print(f"\n" + "=" * 60)
            print(f"📊 RESUMEN TOTAL:")
            print(f"   💰 SOL: {sol_balance:.6f} SOL (${sol_value_usd:.2f} USD)")
            print(f"   🪙 Tokens: ${total_tokens_value_usd:.6f} USD")
            print(f"   💎 TOTAL USD: ${total_value_usd:.2f}")
            print(f"   💎 TOTAL SOL: {total_value_sol:.6f} SOL")
            print("=" * 60)
            
            return {
                'wallet_address': self.wallet_address,
                'sol_balance': sol_balance,
                'sol_price_usd': sol_price_usd,
                'sol_value_usd': sol_value_usd,
                'tokens': token_details,
                'total_tokens_value_usd': total_tokens_value_usd,
                'total_value_usd': total_value_usd,
                'total_value_sol': total_value_sol,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error obteniendo balance detallado: {e}")
            return {}

    def get_current_portfolio(self, include_sol: bool = True) -> PortfolioSnapshot:
        """
        Obtiene snapshot actual del portfolio
        
        Args:
            include_sol: Si incluir balance SOL en el cálculo
            
        Returns:
            PortfolioSnapshot con datos actuales
        """
        try:
            print(f"📊 Obteniendo portfolio actual...")
            
            # Obtener balance SOL
            sol_balance_info = self.account_info.get_balance_info(self.wallet_address)
            sol_balance = sol_balance_info['sol_balance']
            sol_value_usd = sol_balance_info['usd_value']
            
            print(f"💰 Balance SOL: {sol_balance:.6f} SOL (${sol_value_usd:.2f})")
            
            # Obtener tokens del wallet
            token_positions = self._get_token_positions()
            
            # Calcular totales
            total_token_value = sum(pos.current_value_usd for pos in token_positions)
            total_value_usd = total_token_value + (sol_value_usd if include_sol else 0)
            
            # Calcular PnL total
            total_pnl_usd = 0
            total_entry_value = 0
            
            for pos in token_positions:
                if pos.pnl_usd:
                    total_pnl_usd += pos.pnl_usd
                if pos.entry_value_usd:
                    total_entry_value += pos.entry_value_usd
            
            total_pnl_percentage = 0
            if total_entry_value > 0:
                total_pnl_percentage = (total_pnl_usd / total_entry_value) * 100
            
            snapshot = PortfolioSnapshot(
                total_value_usd=total_value_usd,
                sol_balance=sol_balance,
                sol_value_usd=sol_value_usd,
                token_positions=token_positions,
                total_pnl_usd=total_pnl_usd,
                total_pnl_percentage=total_pnl_percentage,
                snapshot_time=datetime.now()
            )
            
            # Guardar en historial
            self.portfolio_history.append(snapshot)
            
            # Mantener solo último mes de historial
            cutoff_date = datetime.now() - timedelta(days=30)
            self.portfolio_history = [
                s for s in self.portfolio_history 
                if s.snapshot_time > cutoff_date
            ]
            
            self._print_portfolio_summary(snapshot)
            
            return snapshot
            
        except Exception as e:
            print(f"❌ Error obteniendo portfolio: {e}")
            return None

    def track_token_entry(self, token_address: str, entry_price: float, 
                         amount_invested: float, notes: str = ""):
        """
        Registra entrada en una posición de token
        
        Args:
            token_address: Dirección del token
            entry_price: Precio de entrada en USD
            amount_invested: Cantidad invertida en USD
            notes: Notas adicionales
        """
        self.position_entries[token_address] = {
            'entry_price': entry_price,
            'amount_invested': amount_invested,
            'timestamp': datetime.now(),
            'notes': notes
        }
        
        print(f"📝 Entrada registrada:")
        print(f"   🪙 Token: {token_address[:8]}...")
        print(f"   💰 Precio entrada: ${entry_price:.10f}")
        print(f"   💵 Invertido: ${amount_invested:.2f}")
        
        self._save_portfolio_data()

    def set_price_alerts(self, token_address: str, profit_target: float = None, 
                        stop_loss: float = None):
        """
        Configura alertas de precio para una posición
        
        Args:
            token_address: Dirección del token
            profit_target: % de ganancia para alerta
            stop_loss: % de pérdida para alerta
        """
        if token_address not in self.position_entries:
            print(f"❌ Token {token_address[:8]}... no está en el portfolio")
            return
        
        entry_data = self.position_entries[token_address]
        entry_price = entry_data['entry_price']
        
        # Calcular precios de alerta
        profit_price = None
        stop_price = None
        
        if profit_target:
            profit_price = entry_price * (1 + profit_target / 100)
        
        if stop_loss:
            stop_price = entry_price * (1 - stop_loss / 100)
        
        # Configurar alertas en el price tracker
        self.price_tracker.set_price_alert(
            token_address=token_address,
            above=profit_price,
            below=stop_price,
            callback=self._price_alert_callback
        )
        
        print(f"🔔 Alertas configuradas para {token_address[:8]}...")
        if profit_price:
            print(f"   📈 Take profit: ${profit_price:.10f} (+{profit_target}%)")
        if stop_price:
            print(f"   📉 Stop loss: ${stop_price:.10f} (-{stop_loss}%)")

    def get_portfolio_performance(self, days: int = 7) -> Dict[str, Any]:
        """
        Obtiene análisis de rendimiento del portfolio
        
        Args:
            days: Días hacia atrás para el análisis
            
        Returns:
            Dict con métricas de rendimiento
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            # Filtrar historial por fecha
            recent_snapshots = [
                s for s in self.portfolio_history 
                if s.snapshot_time > cutoff_date
            ]
            
            if len(recent_snapshots) < 2:
                print(f"❌ No hay suficientes datos para análisis de {days} días")
                return {}
            
            # Calcular métricas
            first_snapshot = recent_snapshots[0]
            last_snapshot = recent_snapshots[-1]
            
            value_change = last_snapshot.total_value_usd - first_snapshot.total_value_usd
            value_change_pct = (value_change / first_snapshot.total_value_usd) * 100
            
            # Mejor y peor valor
            max_value = max(s.total_value_usd for s in recent_snapshots)
            min_value = min(s.total_value_usd for s in recent_snapshots)
            
            performance = {
                'period_days': days,
                'start_value': first_snapshot.total_value_usd,
                'end_value': last_snapshot.total_value_usd,
                'absolute_change': value_change,
                'percentage_change': value_change_pct,
                'max_value': max_value,
                'min_value': min_value,
                'snapshots_count': len(recent_snapshots)
            }
            
            self._print_performance_summary(performance)
            
            return performance
            
        except Exception as e:
            print(f"❌ Error calculando rendimiento: {e}")
            return {}

    def export_portfolio_report(self, filename: str = None) -> str:
        """
        Exporta reporte completo del portfolio
        
        Args:
            filename: Nombre del archivo (opcional)
            
        Returns:
            Nombre del archivo generado
        """
        try:
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"portfolio_report_{self.wallet_address[:8]}_{timestamp}.json"
            
            # Obtener datos actuales
            current_portfolio = self.get_current_portfolio()
            performance_7d = self.get_portfolio_performance(7)
            performance_30d = self.get_portfolio_performance(30)
            
            report = {
                'wallet_address': self.wallet_address,
                'report_timestamp': datetime.now().isoformat(),
                'current_portfolio': current_portfolio.to_dict() if current_portfolio else None,
                'performance_7d': performance_7d,
                'performance_30d': performance_30d,
                'position_entries': {
                    addr: {
                        **data,
                        'timestamp': data['timestamp'].isoformat()
                    }
                    for addr, data in self.position_entries.items()
                },
                'portfolio_history_count': len(self.portfolio_history)
            }
            
            with open(filename, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            
            print(f"📄 Reporte exportado: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Error exportando reporte: {e}")
            return None

    def _get_token_positions(self) -> List[TokenPosition]:
        """Obtiene posiciones actuales de tokens desde la wallet real"""
        positions = []
        
        try:
            # Obtener todos los token accounts reales de la wallet
            token_accounts = self.account_info.get_token_accounts(self.wallet_address)
            
            print(f"🔍 Analizando {len(token_accounts)} token accounts...")
            
            for token_account in token_accounts:
                try:
                    token_address = token_account['mint']
                    balance = float(token_account['balance'])
                    
                    # Filtrar tokens con balance 0
                    if balance <= 0:
                        continue
                    
                    print(f"📊 Procesando token: {token_address[:8]}... (Balance: {balance})")
                    
                    # Obtener precio actual usando price_tracker
                    token_price = self.price_tracker.get_token_price(token_address)
                    
                    if token_price and token_price.price_usd > 0:
                        current_value_usd = balance * token_price.price_usd
                        
                        # Obtener datos de entrada si existen
                        entry_data = self.position_entries.get(token_address)
                        entry_price_usd = None
                        entry_value_usd = None
                        pnl_usd = None
                        pnl_percentage = None
                        
                        if entry_data:
                            entry_price_usd = entry_data['entry_price']
                            entry_value_usd = entry_data['amount_invested']
                            pnl_usd = current_value_usd - entry_value_usd
                            pnl_percentage = (pnl_usd / entry_value_usd) * 100
                        
                        position = TokenPosition(
                            token_address=token_address,
                            symbol=token_price.symbol or f"TOKEN_{token_address[:8]}",
                            name=token_price.name or f"Token {token_address[:8]}",
                            balance=balance,
                            current_price_usd=token_price.price_usd,
                            current_value_usd=current_value_usd,
                            entry_price_usd=entry_price_usd,
                            entry_value_usd=entry_value_usd,
                            pnl_usd=pnl_usd,
                            pnl_percentage=pnl_percentage,
                            last_updated=datetime.now()
                        )
                        
                        positions.append(position)
                        print(f"✅ Token agregado: {position.symbol} - ${current_value_usd:.6f}")
                        
                    else:
                        print(f"⚠️ No se pudo obtener precio para {token_address[:8]}...")
                        
                except Exception as e:
                    print(f"⚠️ Error procesando token {token_account.get('mint', 'N/A')[:8]}...: {e}")
                    continue
        
        except Exception as e:
            print(f"❌ Error obteniendo token accounts: {e}")
        
        print(f"✅ Se encontraron {len(positions)} posiciones con valor")
        return positions

    def _price_alert_callback(self, token_price: TokenPrice, direction: str):
        """Callback para alertas de precio"""
        print(f"\n🚨 ALERTA DE PORTFOLIO 🚨")
        print(f"🪙 Token: {token_price.symbol}")
        print(f"💰 Precio: ${token_price.price_usd:.10f}")
        print(f"📊 Dirección: {direction}")
        
        # Calcular PnL actual si tenemos datos de entrada
        if token_price.address in self.position_entries:
            entry_data = self.position_entries[token_price.address]
            entry_price = entry_data['entry_price']
            pnl_pct = ((token_price.price_usd - entry_price) / entry_price) * 100
            print(f"📈 PnL: {pnl_pct:+.1f}%")
        
        print("🚨" * 20)

    def _print_portfolio_summary(self, snapshot: PortfolioSnapshot):
        """Imprime resumen del portfolio"""
        print(f"\n📊 PORTFOLIO SUMMARY")
        print("=" * 60)
        print(f"💰 Valor Total: ${snapshot.total_value_usd:,.2f}")
        print(f"🪙 SOL: {snapshot.sol_balance:.6f} SOL (${snapshot.sol_value_usd:.2f})")
        print(f"🎯 Tokens: {len(snapshot.token_positions)} posiciones")
        
        if snapshot.total_pnl_usd != 0:
            emoji = "📈" if snapshot.total_pnl_usd > 0 else "📉"
            print(f"{emoji} PnL Total: ${snapshot.total_pnl_usd:+,.2f} ({snapshot.total_pnl_percentage:+.1f}%)")
        
        # Mostrar todas las posiciones de tokens
        if snapshot.token_positions:
            print(f"\n🪙 POSICIONES DE TOKENS:")
            sorted_positions = sorted(snapshot.token_positions, 
                                    key=lambda p: p.current_value_usd, reverse=True)
            
            total_tokens_value = sum(pos.current_value_usd for pos in sorted_positions)
            
            for i, pos in enumerate(sorted_positions, 1):
                pnl_str = ""
                if pos.pnl_percentage is not None:
                    emoji = "📈" if pos.pnl_percentage > 0 else "📉"
                    pnl_str = f" {emoji} {pos.pnl_percentage:+.1f}%"
                
                percentage_of_portfolio = (pos.current_value_usd / snapshot.total_value_usd) * 100
                
                print(f"   {i}. {pos.symbol} ({pos.token_address[:8]}...)")
                print(f"      Balance: {pos.balance:,.6f} tokens")
                print(f"      Precio: ${pos.current_price_usd:.10f}")
                print(f"      Valor: ${pos.current_value_usd:.6f} ({percentage_of_portfolio:.1f}% del portfolio){pnl_str}")
                print()
            
            print(f"📊 Total en Tokens: ${total_tokens_value:.6f} ({(total_tokens_value/snapshot.total_value_usd)*100:.1f}% del portfolio)")
        else:
            print(f"\n🪙 No hay tokens con valor en el portfolio")
        
        print("=" * 60)

    def _print_performance_summary(self, performance: Dict[str, Any]):
        """Imprime resumen de rendimiento"""
        print(f"\n📈 RENDIMIENTO ({performance['period_days']} días)")
        print(f"💰 Valor inicial: ${performance['start_value']:,.2f}")
        print(f"💰 Valor final: ${performance['end_value']:,.2f}")
        
        change = performance['percentage_change']
        emoji = "📈" if change > 0 else "📉"
        print(f"{emoji} Cambio: ${performance['absolute_change']:+,.2f} ({change:+.1f}%)")
        
        print(f"📊 Máximo: ${performance['max_value']:,.2f}")
        print(f"📊 Mínimo: ${performance['min_value']:,.2f}")
        print("-" * 50)

    def _save_portfolio_data(self):
        """Guarda datos del portfolio en archivo"""
        try:
            data = {
                'wallet_address': self.wallet_address,
                'position_entries': {
                    addr: {
                        **entry_data,
                        'timestamp': entry_data['timestamp'].isoformat()
                    }
                    for addr, entry_data in self.position_entries.items()
                },
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.portfolio_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            print(f"⚠️ Error guardando datos: {e}")

    def _load_portfolio_data(self):
        """Carga datos del portfolio desde archivo"""
        try:
            with open(self.portfolio_file, 'r') as f:
                data = json.load(f)
            
            # Cargar entradas de posiciones
            for addr, entry_data in data.get('position_entries', {}).items():
                entry_data['timestamp'] = datetime.fromisoformat(entry_data['timestamp'])
                self.position_entries[addr] = entry_data
            
            print(f"📂 Datos de portfolio cargados: {len(self.position_entries)} posiciones")
            
        except FileNotFoundError:
            print("📂 No se encontraron datos previos del portfolio")
        except Exception as e:
            print(f"⚠️ Error cargando datos: {e}") 