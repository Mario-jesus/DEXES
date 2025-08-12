"""
Funciones de Análisis para BitQuery - Usadas en Notebooks

Basado en las funciones de análisis de BITQUERY_TESTS.ipynb
Completamente asíncrono para mejor rendimiento
"""

from decimal import Decimal, getcontext, ROUND_DOWN
from typing import List, Dict, Any
import asyncio

# Configurar precisión decimal
getcontext().prec = 24


def filter_and_calculate_pnl_corrected(traders_data: List[Dict], min_trades: int = 5, min_profit_percentage: float = 10.0) -> List[Dict]:
    """
    Filtra traders y calcula porcentaje de ganancia - USADO EN BITQUERY_TESTS.ipynb ✅
    
    Args:
        traders_data: Lista de datos de traders
        min_trades: Mínimo número de trades
        min_profit_percentage: Porcentaje mínimo de ganancia
        
    Returns:
        Lista de traders filtrados con métricas calculadas
    """
    filtered_traders = []
    
    for trader in traders_data:
        # Filtrar por mínimo de trades
        if Decimal(trader.get('trades', "0")) < min_trades:
            continue
            
        # Usar cantidades de tokens en lugar de USD para PnL
        bought_tokens = Decimal(trader.get('bought', "0"))
        sold_tokens = Decimal(trader.get('sold', "0"))
        buy_volume_usd = Decimal(trader.get('buyVolumeUsd', "0"))
        sell_volume_usd = Decimal(trader.get('sellVolumeUsd', "0"))
        total_volume_usd = Decimal(trader.get('volumeUsd', "0"))
        
        # Calcular PnL basado en tokens, no en USD
        if bought_tokens > 0 and sold_tokens > 0:
            # PnL basado en cantidad de tokens: (vendido - comprado) / comprado * 100
            token_pnl = ((sold_tokens - bought_tokens) / bought_tokens) * Decimal('100')
            
            # PnL basado en USD (más realista)
            if buy_volume_usd > 0:
                usd_pnl = ((sell_volume_usd - buy_volume_usd) / buy_volume_usd) * Decimal('100')
            else:
                usd_pnl = Decimal('0')
            
            # Usar el PnL más conservador (el menor de los dos)
            realized_pnl = min(token_pnl, usd_pnl) if usd_pnl > 0 else token_pnl
            
            # Limitar PnL a un máximo razonable (ej: 1000%)
            max_reasonable_pnl = Decimal('1000')  # 1000%
            if realized_pnl > max_reasonable_pnl:
                realized_pnl = max_reasonable_pnl
            
            trader['realizedPnlPercentage'] = format(realized_pnl.quantize(Decimal('1.00'), rounding=ROUND_DOWN).normalize(), "f")
            
            # Ratio de trading más conservador
            if buy_volume_usd > 0:
                sell_buy_ratio = sell_volume_usd / buy_volume_usd
                # Limitar ratio a máximo 100
                sell_buy_ratio = min(sell_buy_ratio, Decimal('100'))
                trader['sellBuyRatio'] = format(sell_buy_ratio.quantize(Decimal('1.00'), rounding=ROUND_DOWN).normalize(), "f")
            else:
                trader['sellBuyRatio'] = "0"
            
            # Filtrar por porcentaje mínimo de ganancia
            if realized_pnl >= min_profit_percentage:
                # Calcular métricas adicionales
                trades_count = trader.get('trades', 1)
                if trades_count > 0:
                    trader['avgTradeSize'] = format(Decimal(total_volume_usd / Decimal(trades_count)).quantize(Decimal('1.00'), rounding=ROUND_DOWN).normalize(), "f")
                else:
                    trader['avgTradeSize'] = "0"
                
                # Eficiencia de trading (porcentaje de volumen vendido)
                if total_volume_usd > 0:
                    trading_efficiency = (sell_volume_usd / total_volume_usd) * 100
                    trader['tradingEfficiency'] = format(trading_efficiency.quantize(Decimal('1.00'), rounding=ROUND_DOWN).normalize(), "f")
                else:
                    trader['tradingEfficiency'] = "0"
                
                # Agregar métricas adicionales para debugging
                trader['boughtTokens'] = format(bought_tokens, "f")
                trader['soldTokens'] = format(sold_tokens, "f")
                trader['buyVolumeUSD'] = format(buy_volume_usd, "f")
                trader['sellVolumeUSD'] = format(sell_volume_usd, "f")
                trader['tokenPnL'] = format(token_pnl, "f")
                trader['usdPnL'] = format(usd_pnl, "f")
                
                filtered_traders.append(trader)
    
    # Ordenar por PnL descendente
    filtered_traders.sort(key=lambda x: float(x.get('realizedPnlPercentage', 0)), reverse=True)
    return filtered_traders


def display_trader_analysis(filtered_traders: List[Dict]) -> None:
    """
    Muestra el análisis de traders de forma limpia - USADO EN BITQUERY_TESTS.ipynb ✅
    
    Args:
        filtered_traders: Lista de traders filtrados
    """
    print(f"🎯 Top Traders de Pump.fun (Filtrados)")
    print("=" * 80)
    
    for i, trader in enumerate(filtered_traders, 1):
        owner = trader['Trade']['Account']['Owner']
        symbol = trader['Trade']['Currency']['Symbol']
        name = trader['Trade']['Currency']['Name']
        
        print(f"\n{i}. Trader: {owner[:12]}...")
        print(f"   🪙 Token: {symbol} ({name})")
        print(f"   📊 Total Trades: {trader['trades']}")
        print(f"   🟢 Compras: {trader['buyTrades']} trades (${float(trader['buyVolumeUSD']):,.2f})")
        print(f"   🔴 Ventas: {trader['sellTrades']} trades (${float(trader['sellVolumeUSD']):,.2f})")
        print(f"   💰 PnL: {trader['realizedPnlPercentage']}%")
        print(f"   📈 Ratio V/C: {trader['sellBuyRatio']}")
        print(f"   💵 Promedio Trade: ${trader['avgTradeSize']}")
        print(f"   ⚡ Eficiencia: {trader['tradingEfficiency']}%")


def display_pumpfun_traders(traders: List[Dict]) -> None:
    """
    Muestra traders de Pump.fun de forma limpia - USADO EN BITQUERY_TESTS.ipynb ✅
    
    Args:
        traders: Lista de traders de Pump.fun
    """
    print(f"🚀 Top {len(traders)} traders de Pump.fun:")
    print("=" * 60)
    
    for i, trader in enumerate(traders, 1):
        owner = trader["Trade"]["Account"]["Owner"]
        symbol = trader["Trade"]["Currency"]["Symbol"]
        name = trader["Trade"]["Currency"]["Name"]
        volume_usd = float(trader["volumeUsd"])
        trades = int(trader["trades"])
        bought = float(trader["bought"])
        sold = float(trader["sold"])
        buy_trades = int(trader["buyTrades"])
        sell_trades = int(trader["sellTrades"])
        
        print(f"\n{i}. Trader: {owner}")
        print(f"   🪙 Token: {symbol} ({name})")
        print(f"   💰 Volumen: ${volume_usd:,.2f}")
        print(f"   📊 Total Trades: {trades}")
        print(f"   🟢 Compras: {buy_trades} trades (${bought:,.2f})")
        print(f"   🔴 Ventas: {sell_trades} trades (${sold:,.2f})")
        
        # Calcular métricas adicionales
        if sold > 0:
            buy_sell_ratio = bought / sold
            print(f"   ⚖️ Ratio Compra/Venta: {buy_sell_ratio:.2f}")
        
        avg_trade_size = volume_usd / trades if trades > 0 else 0
        print(f"   💵 Promedio por Trade: ${avg_trade_size:,.2f}")


def analyze_trader_summary(trader_analysis: Dict[str, Any]) -> None:
    """
    Muestra un resumen del análisis de trader - USADO EN NOTEBOOKS ✅
    
    Args:
        trader_analysis: Resultado del análisis de trader
    """
    if "error" in trader_analysis:
        print(f"❌ Error en análisis: {trader_analysis['error']}")
        return
    
    print(f"📊 Análisis de Trader: {trader_analysis['trader_address'][:12]}...")
    print("=" * 60)
    print(f"📈 Total Trades: {trader_analysis['total_trades']}")
    print(f"🟢 Compras: {trader_analysis['total_buys']} (${trader_analysis['buy_volume_usd']:,.2f})")
    print(f"🔴 Ventas: {trader_analysis['total_sells']} (${trader_analysis['sell_volume_usd']:,.2f})")
    print(f"💰 Balance Neto: ${trader_analysis['net_balance']:,.2f}")
    print(f"⚖️ Ratio Compra/Venta: {trader_analysis['buy_sell_ratio']:.2f}")
    
    if trader_analysis.get('recent_buys'):
        print(f"\n🟢 Compras Recientes ({len(trader_analysis['recent_buys'])}):")
        for i, buy in enumerate(trader_analysis['recent_buys'][:3], 1):
            symbol = buy['Trade']['Buy']['Currency']['Symbol']
            amount_usd = buy['Trade']['Buy']['AmountInUSD']
            print(f"   {i}. {symbol}: ${float(amount_usd):,.2f}")
    
    if trader_analysis.get('recent_sells'):
        print(f"\n🔴 Ventas Recientes ({len(trader_analysis['recent_sells'])}):")
        for i, sell in enumerate(trader_analysis['recent_sells'][:3], 1):
            symbol = sell['Trade']['Sell']['Currency']['Symbol']
            amount_usd = sell['Trade']['Sell']['AmountInUSD']
            print(f"   {i}. {symbol}: ${float(amount_usd):,.2f}")


def analyze_token_summary(token_analysis: Dict[str, Any]) -> None:
    """
    Muestra un resumen del análisis de token - USADO EN NOTEBOOKS ✅
    
    Args:
        token_analysis: Resultado del análisis de token
    """
    if "error" in token_analysis:
        print(f"❌ Error en análisis: {token_analysis['error']}")
        return
    
    print(f"🪙 Análisis de Token: {token_analysis['token_mint'][:12]}...")
    print("=" * 60)
    print(f"💰 Volumen Total: ${token_analysis['total_volume_usd']:,.2f}")
    print(f"🟢 Volumen Compras: ${token_analysis['buy_volume_usd']:,.2f}")
    print(f"🔴 Volumen Ventas: ${token_analysis['sell_volume_usd']:,.2f}")
    print(f"📊 Balance Neto: ${token_analysis['net_volume']:,.2f}")
    print(f"👥 Traders Únicos: {token_analysis['unique_traders']}")
    print(f"🔄 Total Trades: {token_analysis['total_trades']}")
    print(f"💵 Promedio por Trade: ${token_analysis['avg_trade_size']:,.2f}")
    
    if token_analysis.get('top_traders'):
        print(f"\n🏆 Top 3 Traders:")
        for i, trader in enumerate(token_analysis['top_traders'][:3], 1):
            owner = trader['Trade']['Account']['Owner']
            volume = float(trader['volumeUsd'])
            trades = trader['trades']
            print(f"   {i}. {owner[:12]}... - ${volume:,.2f} ({trades} trades)")


# === CALLBACKS PARA WEBSOCKET - USADOS EN BITQUERY_WEBSOCKETS.ipynb ===

async def custom_trader_callback(data: Dict, subscription_id: str) -> None:
    """
    Callback personalizado para procesar trades de traders - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅
    """
    if not data or 'data' not in data:
        return
    
    trades = data.get('data', {}).get('Solana', {}).get('DEXTrades', [])
    
    for trade in trades:
        # Determinar si es compra o venta
        buy_data = trade.get('Trade', {}).get('Buy')
        sell_data = trade.get('Trade', {}).get('Sell')
        
        if buy_data and buy_data.get('Amount'):
            side = "🟢 COMPRA"
            amount = float(buy_data.get('Amount', 0))
            amount_usd = float(buy_data.get('AmountInUSD', 0))
            currency = buy_data.get('Currency', {})
            account = buy_data.get('Account', {}).get('Address', '')
            price = float(buy_data.get('Price', 0))
        elif sell_data and sell_data.get('Amount'):
            side = "🔴 VENTA"
            amount = float(sell_data.get('Amount', 0))
            amount_usd = float(sell_data.get('AmountInUSD', 0))
            currency = sell_data.get('Currency', {})
            account = sell_data.get('Account', {}).get('Address', '')
            price = float(sell_data.get('Price', 0))
        else:
            continue
        
        # Información del token
        token_symbol = currency.get('Symbol', 'UNKNOWN')
        token_name = currency.get('Name', 'Unknown Token')
        token_mint = currency.get('MintAddress', '')
        
        # Información del DEX
        dex_info = trade.get('Trade', {}).get('Dex', {})
        dex_name = dex_info.get('ProtocolName', 'UNKNOWN')
        
        # Información del bloque
        block_info = trade.get('Block', {})
        block_time = block_info.get('Time', '')
        
        # Mostrar trade
        print(f"\n{'='*60}")
        print(f"🎯 TRADE DETECTADO [{subscription_id}]")
        print(f"{'='*60}")
        print(f"Trader: {account}")
        print(f"Acción: {side}")
        print(f"Token: {token_symbol} ({token_name})")
        print(f"Mint: {token_mint}")
        print(f"Cantidad: {amount:,.6f} tokens")
        print(f"Valor USD: ${amount_usd:,.2f}")
        print(f"Precio: ${price:.8f}")
        print(f"DEX: {dex_name}")
        print(f"Tiempo: {block_time}")
        print(f"{'='*60}")


async def pumpfun_callback(data: Dict, subscription_id: str) -> None:
    """
    Callback especializado para Pump.fun - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅
    """
    if not data or 'data' not in data:
        return
    
    trades = data.get('data', {}).get('Solana', {}).get('DEXTrades', [])
    
    for trade in trades:
        # Determinar si es compra o venta
        buy_data = trade.get('Trade', {}).get('Buy')
        sell_data = trade.get('Trade', {}).get('Sell')
        
        if buy_data and buy_data.get('Amount'):
            side = "🚀 PUMP BUY"
            amount_usd = float(buy_data.get('AmountInUSD', 0))
            currency = buy_data.get('Currency', {})
            account = buy_data.get('Account', {}).get('Address', '')
        elif sell_data and sell_data.get('Amount'):
            side = "📉 PUMP SELL"
            amount_usd = float(sell_data.get('AmountInUSD', 0))
            currency = sell_data.get('Currency', {})
            account = sell_data.get('Account', {}).get('Address', '')
        else:
            continue
        
        token_symbol = currency.get('Symbol', 'UNKNOWN')
        
        print(f"\n🔥 PUMP.FUN TRADE [{subscription_id}]")
        print(f"{side} - {token_symbol} - ${amount_usd:,.2f} - {account[:8]}...") 