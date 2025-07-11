# -*- coding: utf-8 -*-
"""
DexScreener Portfolio Monitor - Monitoreo de portfolio de tokens
Completamente asíncrono e independiente
"""
import aiohttp
import asyncio
import aiofiles
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from contextlib import asynccontextmanager

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
    Completamente asíncrono e independiente
    """

    def __init__(self, wallet_address: str, price_tracker: DexScreenerPriceTracker, 
                    session: Optional[aiohttp.ClientSession] = None):
        """
        Inicializa el monitor de portfolio
        
        Args:
            wallet_address: Dirección de la wallet a monitorear
            price_tracker: Instancia de DexScreenerPriceTracker
            session: Opcional, sesión HTTP personalizada
        """
        self.wallet_address = wallet_address
        self.price_tracker = price_tracker
        self._session = session
        self._own_session = session is None

        # Configuración
        self.portfolio_history = []
        self.position_entries = {}  # {token_address: {'price': float, 'value': float, 'timestamp': datetime}}

        # Archivo para persistir datos
        self.portfolio_file = f"portfolio_{self.wallet_address[:8]}.json"

        # Estado de tracking
        self._tracking_tasks = set()
        self._running = False

        print("📊 DexScreener Portfolio Monitor inicializado (Async)")
        print(f"📍 Wallet: {self.wallet_address[:8]}...{self.wallet_address[-8:]}")

        # Cargar datos históricos si existen
        asyncio.create_task(self._load_portfolio_data())

    async def __aenter__(self):
        """Context manager entry"""
        if self._own_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()

    async def close(self):
        """Cierra el monitor y limpia recursos"""
        self._running = False

        # Cancelar todas las tareas de tracking
        for task in self._tracking_tasks:
            if not task.done():
                task.cancel()

        # Esperar que terminen las tareas
        if self._tracking_tasks:
            await asyncio.gather(*self._tracking_tasks, return_exceptions=True)
            self._tracking_tasks.clear()

        # Cerrar sesión HTTP si es propia
        if self._own_session and self._session:
            await self._session.close()
            self._session = None

        print("🔒 DexScreener Portfolio Monitor cerrado")

    async def get_detailed_balance(self) -> Dict[str, Any]:
        """
        Obtiene balance detallado mostrando SOL y todos los tokens con sus valores
        
        Returns:
            Dict con información completa de balances
        """
        try:
            print(f"💰 BALANCE DETALLADO DE WALLET")
            print("=" * 60)

            # Obtener balance SOL usando Jupiter Lite API
            sol_balance, sol_price_usd = await self._get_sol_balance()
            sol_value_usd = sol_balance * sol_price_usd

            print(f"🪙 SOL:")
            print(f"   Balance: {sol_balance:.6f} SOL")
            print(f"   Precio: ${sol_price_usd:.2f} USD")
            print(f"   Valor: ${sol_value_usd:.2f} USD")
            print()

            # Obtener tokens usando Solana RPC
            token_accounts = await self._get_token_accounts()
            total_tokens_value_usd = 0
            token_details = []

            print(f"🪙 TOKENS ({len(token_accounts)} encontrados):")

            # Procesar tokens en paralelo
            token_tasks = []
            for token_account in token_accounts:
                task = self._process_token_account(token_account, sol_price_usd)
                token_tasks.append(task)

            token_results = await asyncio.gather(*token_tasks, return_exceptions=True)

            for i, result in enumerate(token_results, 1):
                if isinstance(result, Exception):
                    print(f"   {i}. ❌ Error: {result}")
                elif result:
                    token_details.append(result)
                    total_tokens_value_usd += result['value_usd']
                    print(f"   {i}. ✅ {result['symbol']}: ${result['value_usd']:.6f} USD")

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

    async def get_current_portfolio(self, include_sol: bool = True) -> PortfolioSnapshot:
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
            sol_balance, sol_price_usd = await self._get_sol_balance()
            sol_value_usd = sol_balance * sol_price_usd

            print(f"💰 Balance SOL: {sol_balance:.6f} SOL (${sol_value_usd:.2f})")

            # Obtener tokens del wallet
            token_positions = await self._get_token_positions()

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

            await self._print_portfolio_summary(snapshot)

            return snapshot

        except Exception as e:
            print(f"❌ Error obteniendo portfolio: {e}")
            return None

    async def start_continuous_monitoring(self, update_interval: int = 300, 
                                        callback: Optional[Callable] = None):
        """
        Inicia monitoreo continuo del portfolio
        
        Args:
            update_interval: Intervalo de actualización en segundos
            callback: Función a llamar con el snapshot actualizado
        """
        self._running = True

        async def monitoring_loop():
            while self._running:
                try:
                    snapshot = await self.get_current_portfolio()
                    
                    if callback and snapshot:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(snapshot)
                        else:
                            callback(snapshot)

                    # Esperar antes del siguiente ciclo
                    await asyncio.sleep(update_interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"❌ Error en monitoreo continuo: {e}")
                    await asyncio.sleep(30)  # Pausa antes de reintentar

        task = asyncio.create_task(monitoring_loop())
        self._tracking_tasks.add(task)
        task.add_done_callback(self._tracking_tasks.discard)
        
        print(f"🔄 Monitoreo continuo iniciado (intervalo: {update_interval}s)")

    async def stop_continuous_monitoring(self):
        """Detiene el monitoreo continuo"""
        self._running = False
        print("⏹️ Monitoreo continuo detenido")

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

        asyncio.create_task(self._save_portfolio_data())

    async def set_price_alerts(self, token_address: str, profit_target: float = None, 
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

    async def get_portfolio_performance(self, days: int = 7) -> Dict[str, Any]:
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

            await self._print_performance_summary(performance)

            return performance

        except Exception as e:
            print(f"❌ Error calculando rendimiento: {e}")
            return {}

    async def export_portfolio_report(self, filename: str = None) -> str:
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
            current_portfolio = await self.get_current_portfolio()
            performance_7d = await self.get_portfolio_performance(7)
            performance_30d = await self.get_portfolio_performance(30)

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

            async with aiofiles.open(filename, 'w') as f:
                await f.write(json.dumps(report, indent=2, default=str))

            print(f"📄 Reporte exportado: {filename}")
            return filename

        except Exception as e:
            print(f"❌ Error exportando reporte: {e}")
            return None

    async def _get_sol_balance(self) -> tuple[float, float]:
        """Obtiene balance SOL y precio usando Jupiter Lite API"""
        try:
            # Obtener balance SOL usando Solana RPC
            balance = await self._get_sol_balance_from_rpc()

            # Obtener precio SOL usando Jupiter Lite API
            price = await self._get_sol_price()

            return balance, price
        except Exception as e:
            print(f"⚠️ Error obteniendo balance SOL: {e}")
            return 0.0, 140.0  # Valores por defecto

    async def _get_sol_balance_from_rpc(self) -> float:
        """Obtiene balance SOL usando Solana RPC"""
        try:
            url = "https://api.mainnet-beta.solana.com"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [self.wallet_address]
            }

            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    balance_lamports = data.get('result', {}).get('value', 0)
                    balance_sol = balance_lamports / 1_000_000_000  # Convertir lamports a SOL
                    return balance_sol
                else:
                    return 0.0
        except Exception as e:
            print(f"⚠️ Error obteniendo balance SOL desde RPC: {e}")
            return 0.0

    async def _get_sol_price(self) -> float:
        """Obtiene precio SOL usando Jupiter Lite API"""
        try:
            url = "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['data']['So11111111111111111111111111111111111111112']['price'])
                    return price
                else:
                    return 140.0  # Precio de fallback
        except Exception as e:
            print(f"⚠️ Error obteniendo precio SOL: {e}")
            return 140.0  # Precio de emergencia

    async def _get_token_accounts(self) -> List[Dict]:
        """Obtiene token accounts usando Solana RPC"""
        try:
            url = "https://api.mainnet-beta.solana.com"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    self.wallet_address,
                    {
                        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                    },
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }

            async with self._session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    accounts = data.get('result', {}).get('value', [])

                    token_accounts = []
                    for account in accounts:
                        account_data = account.get('account', {}).get('data', {}).get('parsed', {}).get('info', {})
                        if account_data:
                            token_accounts.append({
                                'mint': account_data.get('mint'),
                                'balance': account_data.get('tokenAmount', {}).get('uiAmount', 0),
                                'decimals': account_data.get('tokenAmount', {}).get('decimals', 0)
                            })

                    return token_accounts
                else:
                    return []
        except Exception as e:
            print(f"⚠️ Error obteniendo token accounts: {e}")
            return []

    async def _process_token_account(self, token_account: Dict, sol_price_usd: float) -> Optional[Dict]:
        """Procesa un token account individual"""
        try:
            token_address = token_account['mint']
            balance = float(token_account['balance'])
            decimals = token_account['decimals']

            if balance <= 0:
                return None

            # Obtener precio usando price tracker
            token_price = await self.price_tracker.get_token_price(token_address)

            if token_price and token_price.price_usd > 0:
                value_usd = balance * token_price.price_usd
                value_sol = value_usd / sol_price_usd if sol_price_usd > 0 else 0

                return {
                    'address': token_address,
                    'symbol': token_price.symbol or f"TOKEN_{token_address[:8]}",
                    'name': token_price.name or "Unknown Token",
                    'balance': balance,
                    'decimals': decimals,
                    'price_usd': token_price.price_usd,
                    'value_usd': value_usd,
                    'value_sol': value_sol
                }
            else:
                return None

        except Exception as e:
            print(f"⚠️ Error procesando token {token_account.get('mint', 'N/A')[:8]}...: {e}")
            return None

    async def _get_token_positions(self) -> List[TokenPosition]:
        """Obtiene posiciones actuales de tokens desde la wallet real"""
        positions = []

        try:
            # Obtener todos los token accounts reales de la wallet
            token_accounts = await self._get_token_accounts()

            print(f"🔍 Analizando {len(token_accounts)} token accounts...")

            # Procesar tokens en paralelo
            position_tasks = []
            for token_account in token_accounts:
                task = self._create_token_position(token_account)
                position_tasks.append(task)

            position_results = await asyncio.gather(*position_tasks, return_exceptions=True)

            for result in position_results:
                if isinstance(result, TokenPosition):
                    positions.append(result)
                    print(f"✅ Token agregado: {result.symbol} - ${result.current_value_usd:.6f}")
                elif isinstance(result, Exception):
                    print(f"⚠️ Error procesando token: {result}")

        except Exception as e:
            print(f"❌ Error obteniendo token accounts: {e}")

        print(f"✅ Se encontraron {len(positions)} posiciones con valor")
        return positions

    async def _create_token_position(self, token_account: Dict) -> Optional[TokenPosition]:
        """Crea una posición de token desde token account"""
        try:
            token_address = token_account['mint']
            balance = float(token_account['balance'])

            # Filtrar tokens con balance 0
            if balance <= 0:
                return None

            # Obtener precio actual usando price_tracker
            token_price = await self.price_tracker.get_token_price(token_address)

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

                return position
            else:
                print(f"⚠️ No se pudo obtener precio para {token_address[:8]}...")
                return None

        except Exception as e:
            print(f"⚠️ Error procesando token {token_account.get('mint', 'N/A')[:8]}...: {e}")
            return None

    async def _price_alert_callback(self, token_price: TokenPrice, direction: str):
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

    async def _print_portfolio_summary(self, snapshot: PortfolioSnapshot):
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

    async def _print_performance_summary(self, performance: Dict[str, Any]):
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

    async def _save_portfolio_data(self):
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

            async with aiofiles.open(self.portfolio_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))

        except Exception as e:
            print(f"⚠️ Error guardando datos: {e}")

    async def _load_portfolio_data(self):
        """Carga datos del portfolio desde archivo"""
        try:
            async with aiofiles.open(self.portfolio_file, 'r') as f:
                content = await f.read()
                data = json.loads(content)

            # Cargar entradas de posiciones
            for addr, entry_data in data.get('position_entries', {}).items():
                entry_data['timestamp'] = datetime.fromisoformat(entry_data['timestamp'])
                self.position_entries[addr] = entry_data

            print(f"📂 Datos de portfolio cargados: {len(self.position_entries)} posiciones")

        except FileNotFoundError:
            print("📂 No se encontraron datos previos del portfolio")
        except Exception as e:
            print(f"⚠️ Error cargando datos: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado del portfolio monitor"""
        return {
            'wallet_address': self.wallet_address,
            'position_entries_count': len(self.position_entries),
            'portfolio_history_count': len(self.portfolio_history),
            'tracking_tasks': len(self._tracking_tasks),
            'is_running': self._running,
            'session_active': self._session is not None
        }
