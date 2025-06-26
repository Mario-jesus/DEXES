# -*- coding: utf-8 -*-
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from solders.keypair import Keypair
from solders.pubkey import Pubkey as PublicKey
from solders.transaction import Transaction, VersionedTransaction
from solana_manager.wallet_manager import SolanaWalletManager


class JupiterDEX:
    """Integración completa con Jupiter DEX para bots y arbitraje"""
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        self.wallet_manager = wallet_manager
        self.client = wallet_manager.client
        # URLs actualizadas para 2025 - Jupiter APIs
        self.quote_api = "https://quote-api.jup.ag/v6"
        self.price_api = "https://lite-api.jup.ag/price/v2"
        
        # Tokens principales de Solana (incluyendo MEOW)
        self.tokens = {
            'SOL': 'So11111111111111111111111111111111111111112',
            'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
            'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
            'RAY': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
            'ORCA': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
            'BONK': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
            'WIF': 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
            'MEOW': 'HhFrYr7WbSwBzvX5AJ6rkRL9wLKrx8cJsmUceFvgnHkA'
        }
        
        print(f"🪐 Jupiter DEX inicializado en {wallet_manager.network}")

    def get_token_price(self, token_symbol: str) -> Optional[float]:
        """Obtiene el precio actual de un token con múltiples fuentes"""
        try:
            token_address = self.tokens.get(token_symbol.upper())
            if not token_address:
                print(f"❌ Token {token_symbol} no encontrado en tokens conocidos")
                return None
            
            # Intentar múltiples APIs en orden de preferencia
            price_apis = [
                {
                    'name': 'Jupiter',
                    'url': f"{self.price_api}",
                    'params': {'ids': token_address},
                    'parser': lambda data: data['data'][token_address]['price'] if 'data' in data and token_address in data['data'] else None
                },
                {
                    'name': 'CoinGecko',
                    'url': 'https://api.coingecko.com/api/v3/simple/token_price/solana',
                    'params': {'contract_addresses': token_address, 'vs_currencies': 'usd'},
                    'parser': lambda data: data[token_address]['usd'] if token_address in data and 'usd' in data[token_address] else None
                },
                {
                    'name': 'Birdeye',
                    'url': f'https://public-api.birdeye.so/defi/price',
                    'params': {'address': token_address},
                    'parser': lambda data: data['data']['value'] if 'data' in data and 'value' in data['data'] else None
                }
            ]
            
            # Intentar cada API con manejo robusto de errores
            for api in price_apis:
                try:
                    print(f"🔄 Intentando obtener precio desde {api['name']}...")
                    
                    response = requests.get(api['url'], params=api['params'], timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Verificar si la respuesta tiene datos válidos
                        if not data:
                            print(f"⚠️ {api['name']}: respuesta vacía")
                            continue
                            
                        price = api['parser'](data)
                        
                        if price:
                            try:
                                price = float(price)
                                if price > 0:
                                    print(f"💰 Precio {token_symbol}: ${price:.6f} (desde {api['name']})")
                                    return price
                                else:
                                    print(f"⚠️ {api['name']}: precio cero")
                            except (ValueError, TypeError):
                                print(f"⚠️ {api['name']}: precio no numérico")
                        else:
                            print(f"⚠️ {api['name']}: precio inválido o cero")
                    
                    else:
                        print(f"⚠️ {api['name']} no disponible (status: {response.status_code})")
                    
                except requests.exceptions.Timeout:
                    print(f"⚠️ {api['name']}: timeout")
                    continue
                except requests.exceptions.RequestException as e:
                    print(f"⚠️ {api['name']}: error de conexión - {str(e)[:30]}...")
                    continue
                except Exception as e:
                    print(f"⚠️ Error con {api['name']}: {str(e)[:50]}...")
                    continue
            
            # Fallback: usar cotización de Jupiter si las APIs de precio fallan
            print(f"🔄 Fallback: usando cotización Jupiter para {token_symbol}...")
            return self._get_price_from_quote(token_symbol)
            
        except Exception as e:
            print(f"❌ Error obteniendo precio: {e}")
            return None

    def get_token_price_by_address(self, token_address: str) -> Optional[float]:
        """Obtiene precio de un token por su dirección (para tokens no conocidos)"""
        try:
            print(f"🔍 Obteniendo precio por dirección: {token_address[:8]}...")
            
            # APIs que aceptan direcciones directamente
            address_apis = [
                {
                    'name': 'Jupiter',
                    'url': f"{self.price_api}",
                    'params': {'ids': token_address},
                    'parser': lambda data: data['data'][token_address]['price'] if 'data' in data and token_address in data['data'] else None
                },
                {
                    'name': 'CoinGecko',
                    'url': 'https://api.coingecko.com/api/v3/simple/token_price/solana',
                    'params': {'contract_addresses': token_address, 'vs_currencies': 'usd'},
                    'parser': lambda data: data[token_address]['usd'] if token_address in data and 'usd' in data[token_address] else None
                },
                {
                    'name': 'Birdeye',
                    'url': f'https://public-api.birdeye.so/defi/price',
                    'params': {'address': token_address},
                    'parser': lambda data: data['data']['value'] if 'data' in data and 'value' in data['data'] else None
                }
            ]
            
            for api in address_apis:
                try:
                    print(f"🔄 Intentando {api['name']}...")
                    
                    response = requests.get(api['url'], params=api['params'], timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        price = api['parser'](data)
                        
                        if price:
                            try:
                                price = float(price)
                                if price > 0:
                                    print(f"💰 Precio token: ${price:.12f} (desde {api['name']})")
                                    return price
                                else:
                                    print(f"⚠️ {api['name']}: precio cero")
                            except (ValueError, TypeError):
                                print(f"⚠️ {api['name']}: precio no numérico")
                
                except Exception as e:
                    print(f"⚠️ Error con {api['name']}: {str(e)[:30]}...")
                    continue
            
            print(f"❌ No se pudo obtener precio para {token_address[:8]}...")
            return None
            
        except Exception as e:
            print(f"❌ Error obteniendo precio por dirección: {e}")
            return None

    def _get_price_from_quote(self, token_symbol: str) -> Optional[float]:
        """Obtiene precio usando cotización de Jupiter (fallback)"""
        try:
            token_upper = token_symbol.upper()
            
            if token_upper == 'SOL':
                # Para SOL, usar USDC como referencia
                quote = self.get_quote('SOL', 'USDC', 1.0)
                if quote and 'readable_output' in quote:
                    price = quote['readable_output']
                    print(f"💰 Precio SOL: ${price:.6f} (desde cotización)")
                    return price
                    
            elif token_upper in ['USDC', 'USDT']:
                # Para stablecoins, usar SOL como referencia inversa
                print(f"🔄 Obteniendo precio {token_symbol} usando referencia SOL...")
                quote = self.get_quote('SOL', token_symbol, 1.0)
                if quote and 'readable_output' in quote:
                    # Si 1 SOL = X USDC, entonces 1 USDC = 1/X SOL en USD
                    sol_to_stablecoin = quote['readable_output']
                    if sol_to_stablecoin > 0:
                        # El precio del stablecoin en USD es aproximadamente 1/ratio_SOL_to_stablecoin * precio_SOL
                        sol_price = self._get_sol_price_simple()
                        if sol_price:
                            stablecoin_price = sol_price / sol_to_stablecoin
                            print(f"💰 Precio {token_symbol}: ${stablecoin_price:.6f} (calculado desde SOL)")
                            return stablecoin_price
                
                # Si falla la cotización, intentar APIs directas para stablecoins
                return self._get_stablecoin_price_direct(token_symbol)
                
            else:
                # Para otros tokens, convertir a SOL y luego a USD
                quote_to_sol = self.get_quote(token_symbol, 'SOL', 1.0)
                if quote_to_sol and 'readable_output' in quote_to_sol:
                    sol_amount = quote_to_sol['readable_output']
                    sol_price = self._get_sol_price_simple()
                    
                    if sol_price:
                        token_price = sol_amount * sol_price
                        print(f"💰 Precio {token_symbol}: ${token_price:.6f} (calculado)")
                        return token_price
            
            return None
            
        except Exception as e:
            print(f"❌ Error en fallback de precio: {e}")
            return None

    def _get_stablecoin_price_direct(self, token_symbol: str) -> Optional[float]:
        """Obtiene precio de stablecoin usando APIs directas como último recurso"""
        try:
            token_upper = token_symbol.upper()
            
            # APIs específicas para stablecoins
            stablecoin_apis = []
            
            if token_upper == 'USDC':
                stablecoin_apis = [
                    {
                        'name': 'CoinGecko USDC',
                        'url': 'https://api.coingecko.com/api/v3/simple/price',
                        'params': {'ids': 'usd-coin', 'vs_currencies': 'usd'},
                        'parser': lambda data: data['usd-coin']['usd'] if 'usd-coin' in data else None
                    },
                    {
                        'name': 'CryptoCompare USDC',
                        'url': 'https://min-api.cryptocompare.com/data/price',
                        'params': {'fsym': 'USDC', 'tsyms': 'USD'},
                        'parser': lambda data: data['USD'] if 'USD' in data else None
                    }
                ]
            elif token_upper == 'USDT':
                stablecoin_apis = [
                    {
                        'name': 'CoinGecko USDT',
                        'url': 'https://api.coingecko.com/api/v3/simple/price',
                        'params': {'ids': 'tether', 'vs_currencies': 'usd'},
                        'parser': lambda data: data['tether']['usd'] if 'tether' in data else None
                    },
                    {
                        'name': 'CryptoCompare USDT',
                        'url': 'https://min-api.cryptocompare.com/data/price',
                        'params': {'fsym': 'USDT', 'tsyms': 'USD'},
                        'parser': lambda data: data['USD'] if 'USD' in data else None
                    }
                ]
            
            # Intentar cada API
            for api in stablecoin_apis:
                try:
                    print(f"🔄 Intentando {api['name']}...")
                    response = requests.get(api['url'], params=api['params'], timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        price = api['parser'](data)
                        
                        if price:
                            price = float(price)
                            print(f"💰 Precio {token_symbol}: ${price:.6f} (desde {api['name']})")
                            return price
                
                except Exception as e:
                    print(f"⚠️ Error con {api['name']}: {str(e)[:30]}...")
                    continue
            
            # Último recurso: precio aproximado basado en naturaleza del stablecoin
            print(f"⚠️ Usando precio aproximado para {token_symbol}: $1.00")
            return 1.0
            
        except Exception as e:
            print(f"❌ Error obteniendo precio directo de stablecoin: {e}")
            return 1.0  # Fallback seguro para stablecoins

    def _get_sol_price_simple(self) -> Optional[float]:
        """Obtiene precio de SOL de forma simple"""
        try:
            # Usar APIs públicas simples para SOL
            simple_apis = [
                'https://api.coinbase.com/v2/exchange-rates?currency=SOL',
                'https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT'
            ]
            
            for api_url in simple_apis:
                try:
                    response = requests.get(api_url, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        
                        if 'coinbase.com' in api_url:
                            if 'data' in data and 'rates' in data['data'] and 'USD' in data['data']['rates']:
                                return float(data['data']['rates']['USD'])
                        
                        elif 'binance.com' in api_url:
                            if 'price' in data:
                                return float(data['price'])
                
                except Exception:
                    continue
            
            # Último fallback: precio fijo aproximado (solo para emergencias)
            print("⚠️ Usando precio SOL aproximado: $140")
            return 140.0
            
        except Exception:
            return 140.0  # Precio de emergencia

    def get_quote(self, input_token: str, output_token: str, amount: float, slippage: float = 0.5) -> Optional[Dict]:
        """Obtiene cotización para un swap"""
        try:
            input_mint = self.tokens.get(input_token.upper())
            output_mint = self.tokens.get(output_token.upper())
            
            if not input_mint or not output_mint:
                print(f"❌ Tokens no válidos: {input_token} -> {output_token}")
                return None
            
            # Convertir amount según decimales (SOL = 9, USDC = 6)
            if input_token.upper() == 'SOL':
                amount_lamports = int(amount * 1_000_000_000)
            elif input_token.upper() in ['USDC', 'USDT']:
                amount_lamports = int(amount * 1_000_000)
            else:
                amount_lamports = int(amount * 1_000_000_000)  # Default 9 decimals
            
            url = f"{self.quote_api}/quote"
            params = {
                'inputMint': input_mint,
                'outputMint': output_mint,
                'amount': amount_lamports,
                'slippageBps': int(slippage * 100)  # Convert to basis points
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                quote = response.json()
                
                # Calcular amounts legibles
                if output_token.upper() == 'SOL':
                    output_amount = int(quote['outAmount']) / 1_000_000_000
                elif output_token.upper() in ['USDC', 'USDT']:
                    output_amount = int(quote['outAmount']) / 1_000_000
                else:
                    output_amount = int(quote['outAmount']) / 1_000_000_000
                
                print(f"📊 Cotización: {amount} {input_token} → {output_amount:.6f} {output_token}")
                
                # Mostrar información de la ruta de manera segura
                route_plan = quote.get('routePlan', [])
                if route_plan:
                    try:
                        # Intentar mostrar información de la ruta
                        route_info = []
                        for step in route_plan:
                            if isinstance(step, dict):
                                # Buscar diferentes campos posibles para el nombre del DEX
                                dex_name = step.get('label') or step.get('swapInfo', {}).get('label') or step.get('ammKey', 'DEX')[:8]
                                route_info.append(str(dex_name))
                        
                        if route_info:
                            print(f"🛣️  Ruta: {' → '.join(route_info)}")
                    except Exception as route_error:
                        print(f"🛣️  Ruta: {len(route_plan)} pasos")
                
                quote['readable_output'] = output_amount
                return quote
            else:
                print(f"❌ Error en cotización: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error obteniendo cotización: {e}")
            return None

    def execute_swap(self, keypair: Keypair, quote: Dict) -> Optional[str]:
        """Ejecuta un swap usando una cotización de Jupiter"""
        try:
            print("🔄 Ejecutando swap...")
            
            # Obtener transacción serializada de Jupiter
            swap_url = f"{self.quote_api}/swap"
            
            swap_data = {
                'quoteResponse': quote,
                'userPublicKey': str(keypair.pubkey()),
                'wrapAndUnwrapSol': True,
                'dynamicComputeUnitLimit': True,
                'prioritizationFeeLamports': 'auto'
            }
            
            response = requests.post(swap_url, json=swap_data, timeout=30)
            
            if response.status_code != 200:
                print(f"❌ Error obteniendo transacción: {response.status_code}")
                return None
            
            swap_response = response.json()
            
            # Verificar si hay errores de simulación
            if 'simulationError' in swap_response and swap_response['simulationError']:
                print(f"⚠️ Error de simulación: {swap_response['simulationError']}")
                print("💡 La transacción podría fallar, pero continuando...")
            
            # Deserializar y firmar transacción
            import base64
            try:
                transaction_bytes = base64.b64decode(swap_response['swapTransaction'])
                print(f"📏 Transacción decodificada: {len(transaction_bytes)} bytes")
                
                # Usar VersionedTransaction en lugar de Transaction para mejor compatibilidad
                transaction = VersionedTransaction.from_bytes(transaction_bytes)
                
                # Firmar transacción
                transaction.sign([keypair])
                
                print("✅ Transacción firmada exitosamente")
                
            except Exception as tx_error:
                print(f"❌ Error procesando transacción: {tx_error}")
                print("🔄 Intentando con Transaction legacy...")
                
                try:
                    # Fallback a Transaction normal
                    transaction = Transaction.from_bytes(transaction_bytes)
                    transaction.sign([keypair])
                    print("✅ Transacción legacy firmada exitosamente")
                except Exception as legacy_error:
                    print(f"❌ Error con transacción legacy: {legacy_error}")
                    return None
            
            # Enviar transacción
            result = self.client.send_transaction(transaction)
            
            if result.value:
                signature = str(result.value)
                print("🎉 ¡Swap ejecutado exitosamente!")
                print(f"🔗 Signature: {signature}")
                print(f"🌐 Explorer: https://explorer.solana.com/tx/{signature}?cluster={self.wallet_manager.network}")
                return signature
            else:
                print("❌ Error enviando transacción")
                return None
                
        except Exception as e:
            print(f"❌ Error ejecutando swap: {e}")
            return None

    def swap_tokens(self, keypair: Keypair, input_token: str, output_token: str, 
                    amount: float, slippage: float = 0.5) -> Optional[str]:
        """Función completa para hacer swap de tokens"""
        print(f"🔄 Iniciando swap: {amount} {input_token} → {output_token}")
        
        # Obtener cotización
        quote = self.get_quote(input_token, output_token, amount, slippage)
        
        if not quote:
            print("❌ No se pudo obtener cotización")
            return None
        
        # Ejecutar swap
        signature = self.execute_swap(keypair, quote)
        
        return signature

    def find_arbitrage_opportunities(self, token_pairs: List[Tuple[str, str]], 
                                    min_profit_usd: float = 1.0) -> List[Dict]:
        """Busca oportunidades de arbitraje entre diferentes rutas"""
        print(f"🔍 Buscando arbitraje (min profit: ${min_profit_usd})")
        opportunities = []
        
        for token_a, token_b in token_pairs:
            try:
                # Obtener precio A → B
                quote_ab = self.get_quote(token_a, token_b, 100)  # 100 units test
                
                # Obtener precio B → A
                if quote_ab:
                    output_amount = quote_ab['readable_output']
                    quote_ba = self.get_quote(token_b, token_a, output_amount)
                    
                    if quote_ba:
                        final_amount = quote_ba['readable_output']
                        profit = final_amount - 100
                        
                        if profit > 0:
                            # Calcular profit en USD
                            token_a_price = self.get_token_price(token_a)
                            if token_a_price:
                                profit_usd = profit * token_a_price
                                
                                if profit_usd >= min_profit_usd:
                                    opportunity = {
                                        'pair': f"{token_a}/{token_b}",
                                        'profit_tokens': profit,
                                        'profit_usd': profit_usd,
                                        'profit_percentage': (profit / 100) * 100,
                                        'route_1': quote_ab,
                                        'route_2': quote_ba,
                                        'timestamp': datetime.now().isoformat()
                                    }
                                    
                                    opportunities.append(opportunity)
                                    print(f"💰 Arbitraje encontrado: {token_a}/{token_b}")
                                    print(f"   Profit: {profit:.4f} {token_a} (${profit_usd:.2f})")
                
            except Exception as e:
                print(f"❌ Error buscando arbitraje {token_a}/{token_b}: {e}")
                continue
        
        print(f"✅ Encontradas {len(opportunities)} oportunidades")
        return opportunities

    def execute_arbitrage(self, keypair: Keypair, opportunity: Dict, 
                            amount: float) -> Optional[List[str]]:
        """Ejecuta una oportunidad de arbitraje"""
        print(f"⚡ Ejecutando arbitraje: {opportunity['pair']}")
        
        signatures = []
        
        try:
            # Extraer tokens del par
            token_a, token_b = opportunity['pair'].split('/')
            
            # Primer swap: A → B
            print(f"1️⃣ Swap 1: {amount} {token_a} → {token_b}")
            sig1 = self.swap_tokens(keypair, token_a, token_b, amount)
            
            if not sig1:
                print("❌ Falló el primer swap")
                return None
            
            signatures.append(sig1)
            
            # Esperar confirmación (simplificado)
            print("⏳ Esperando confirmación del primer swap...")
            
            # Segundo swap: B → A (usando el output del primero)
            output_amount = opportunity['route_1']['readable_output'] * (amount / 100)
            
            print(f"2️⃣ Swap 2: {output_amount:.6f} {token_b} → {token_a}")
            sig2 = self.swap_tokens(keypair, token_b, token_a, output_amount)
            
            if not sig2:
                print("❌ Falló el segundo swap")
                return signatures  # Retornar el primer signature al menos
            
            signatures.append(sig2)
            
            print("🎉 ¡Arbitraje completado!")
            print(f"📊 Profit esperado: {opportunity['profit_usd']:.2f} USD")
            
            return signatures
            
        except Exception as e:
            print(f"❌ Error ejecutando arbitraje: {e}")
            return signatures if signatures else None

    def monitor_prices(self, tokens: List[str], alert_threshold: float = 5.0) -> Dict[str, float]:
        """Monitorea precios y detecta cambios significativos"""
        print(f"👁️ Monitoreando precios (threshold: {alert_threshold}%)")
        
        current_prices = {}
        
        for token in tokens:
            price = self.get_token_price(token)
            if price:
                current_prices[token] = price
        
        # Aquí podrías comparar con precios anteriores y alertar
        # Por ahora solo retornamos los precios actuales
        
        return current_prices

    def get_pool_info(self, token_a: str, token_b: str) -> Optional[Dict]:
        """Obtiene información de liquidez de un par"""
        try:
            # Usar quote para obtener info de rutas
            quote = self.get_quote(token_a, token_b, 1)
            
            if quote and 'routePlan' in quote:
                pools_info = []
                
                for route in quote['routePlan']:
                    pool_info = {
                        'dex': route['swapInfo']['label'],
                        'input_mint': route['swapInfo']['inputMint'],
                        'output_mint': route['swapInfo']['outputMint'],
                        'fee_bps': route['swapInfo'].get('feeAmount', 0),
                        'fee_mint': route['swapInfo'].get('feeMint', 'N/A')
                    }
                    pools_info.append(pool_info)
                
                return {
                    'pair': f"{token_a}/{token_b}",
                    'pools': pools_info,
                    'total_routes': len(pools_info)
                }
        
        except Exception as e:
            print(f"❌ Error obteniendo info de pool: {e}")
        
        return None

print("✅ Módulo Jupiter DEX creado")
print("🚀 Funcionalidades disponibles:")
print("   - Swaps automáticos")
print("   - Búsqueda de arbitraje")
print("   - Monitoreo de precios")
print("   - Información de pools") 