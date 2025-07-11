"""
Queries GraphQL Centralizadas - Solo las que se usan en los notebooks

Basado en el análisis de BITQUERY_TESTS.ipynb y BITQUERY_WEBSOCKETS.ipynb
"""

from typing import List
from datetime import datetime


class BitQueryQueries:
    """Queries HTTP para consultas estáticas"""

    @staticmethod
    def get_top_traders_for_token(token_mint: str, limit: int = 50) -> str:
        """Top traders de un token específico - USADO EN NOTEBOOKS ✅"""
        return f"""
        query TopTraders {{
            Solana(network: solana) {{
                DEXTradeByTokens(
                    orderBy: {{descendingByField: "volumeUsd"}}
                    limit: {{count: {limit}}}
                    where: {{
                        Trade: {{
                            Currency: {{MintAddress: {{is: "{token_mint}"}}}}
                        }}, 
                        Transaction: {{Result: {{Success: true}}}}
                    }}
                ) {{
                    Trade {{
                        Account {{
                            Owner
                        }}
                        Currency {{
                            Symbol
                            Name
                            MintAddress
                        }}
                        Dex {{
                            ProgramAddress
                            ProtocolFamily
                            ProtocolName
                        }}
                    }}
                    bought: sum(of: Trade_Amount, if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sold: sum(of: Trade_Amount, if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                    volume: sum(of: Trade_Amount)
                    volumeUsd: sum(of: Trade_Side_AmountInUSD)
                    buyVolumeUsd: sum(of: Trade_Side_AmountInUSD, if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sellVolumeUsd: sum(of: Trade_Side_AmountInUSD, if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                    trades: count
                    buyTrades: count(if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sellTrades: count(if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                }}
            }}
        }}
        """

    @staticmethod
    def get_pumpfun_top_traders_filtered(
        limit: int = 5,
        time_from: str = None,
        time_to: str = None
    ) -> str:
        """Top traders de Pump.fun con filtros - USADO EN BITQUERY_TESTS.ipynb ✅"""
        
        # Construir filtro de tiempo
        time_filter = ""
        if time_from and time_to:
            start_date = datetime.strptime(time_from, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
            end_date = datetime.strptime(time_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            time_filter = f'Block: {{Time: {{since: "{start_date.isoformat()}Z", till: "{end_date.isoformat()}Z"}}}}'
        elif time_from:
            start_date = datetime.strptime(time_from, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
            time_filter = f'Block: {{Time: {{since: "{start_date.isoformat()}Z"}}}}'
        elif time_to:
            end_date = datetime.strptime(time_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            time_filter = f'Block: {{Time: {{till: "{end_date.isoformat()}Z"}}}}'

        return f"""
        query PumpFunTopTradersFiltered {{
            Solana(network: solana) {{
                DEXTradeByTokens(
                    orderBy: {{descendingByField: "volumeUsd"}}
                    limit: {{count: {limit}}}
                    where: {{
                        Trade: {{
                            Dex: {{ProtocolName: {{is: "pump"}}}}
                        }},
                        Transaction: {{Result: {{Success: true}}}},
                        {time_filter}
                    }}
                ) {{
                    Trade {{
                        Account {{
                            Owner
                        }}
                        Currency {{
                            Symbol
                            Name
                            MintAddress
                        }}
                        Dex {{
                            ProtocolName
                        }}
                    }}
                    bought: sum(of: Trade_Amount, if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sold: sum(of: Trade_Amount, if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                    volume: sum(of: Trade_Amount)
                    volumeUsd: sum(of: Trade_Side_AmountInUSD)
                    buyVolumeUsd: sum(of: Trade_Side_AmountInUSD, if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sellVolumeUsd: sum(of: Trade_Side_AmountInUSD, if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                    trades: count
                    buyTrades: count(if: {{Trade: {{Side: {{Type: {{is: buy}}}}}}}})
                    sellTrades: count(if: {{Trade: {{Side: {{Type: {{is: sell}}}}}}}})
                }}
            }}
        }}
        """

    @staticmethod
    def get_trader_buys(trader_address: str, limit: int = 100) -> str:
        """Compras de un trader específico - USADO EN NOTEBOOKS ✅"""
        return f"""
        query TraderBuys {{
            Solana(network: solana) {{
                DEXTrades(
                    orderBy: {{descending: Block_Time}}
                    limit: {{count: {limit}}}
                    where: {{
                        Trade: {{
                            Buy: {{Account: {{Address: {{is: "{trader_address}"}}}}}}
                        }},
                        Transaction: {{Result: {{Success: true}}}}
                    }}
                ) {{
                    Block {{
                        Time
                    }}
                    Transaction {{
                        Signature
                    }}
                    Trade {{
                        Buy {{
                            Amount
                            AmountInUSD
                            Currency {{
                                Symbol
                                MintAddress
                            }}
                            Account {{
                                Address
                            }}
                        }}
                        Dex {{
                            ProtocolName
                        }}
                    }}
                }}
            }}
        }}
        """

    @staticmethod
    def get_trader_sells(trader_address: str, limit: int = 100) -> str:
        """Ventas de un trader específico - USADO EN NOTEBOOKS ✅"""
        return f"""
        query TraderSells {{
            Solana(network: solana) {{
                DEXTrades(
                    orderBy: {{descending: Block_Time}}
                    limit: {{count: {limit}}}
                    where: {{
                        Trade: {{
                            Sell: {{Account: {{Address: {{is: "{trader_address}"}}}}}}
                        }},
                        Transaction: {{Result: {{Success: true}}}}
                    }}
                ) {{
                    Block {{
                        Time
                    }}
                    Transaction {{
                        Signature
                    }}
                    Trade {{
                        Sell {{
                            Amount
                            AmountInUSD
                            Currency {{
                                Symbol
                                MintAddress
                            }}
                            Account {{
                                Address
                            }}
                        }}
                        Dex {{
                            ProtocolName
                        }}
                    }}
                }}
            }}
        }}
        """


class BitQuerySubscriptions:
    """Suscripciones WebSocket para tiempo real"""

    @staticmethod
    def track_trader_realtime(trader_address: str) -> str:
        """Trackear trader en tiempo real - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅"""
        return f"""
        subscription TrackTraderRealtime {{
            Solana {{
                DEXTrades(
                    where: {{
                        Transaction: {{
                            Result: {{Success: true}},
                            Signer: {{is: "{trader_address}"}}
                        }}
                    }}
                ) {{
                    Block {{
                        Time
                        Height
                        Slot
                    }}
                    Trade {{
                        Dex {{
                            ProgramAddress
                            ProtocolFamily
                            ProtocolName
                        }}
                        Buy {{
                            Amount
                            AmountInUSD
                            Account {{
                                Address
                            }}
                            Currency {{
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }}
                            Price
                        }}
                        Sell {{
                            Amount
                            AmountInUSD
                            Account {{
                                Address
                            }}
                            Currency {{
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }}
                            Price
                        }}
                        Market {{
                            MarketAddress
                        }}
                    }}
                    Transaction {{
                        Signature
                        Signer
                        Fee
                    }}
                }}
            }}
        }}
        """

    @staticmethod
    def track_pumpfun_realtime(min_amount_usd: float = 100) -> str:
        """Trackear Pump.fun en tiempo real - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅"""
        return f"""
        subscription TrackPumpFunRealtime {{
            Solana {{
                DEXTrades(
                    where: {{
                        Transaction: {{Result: {{Success: true}}}},
                        Trade: {{
                            Dex: {{ProtocolName: {{is: "pump"}}}},
                            any: [
                                {{Buy: {{AmountInUSD: {{gt: {min_amount_usd}}}}}}},
                                {{Sell: {{AmountInUSD: {{gt: {min_amount_usd}}}}}}}
                            ]
                        }}
                    }}
                ) {{
                    Block {{
                        Time
                        Height
                        Slot
                    }}
                    Trade {{
                        Dex {{
                            ProgramAddress
                            ProtocolFamily
                            ProtocolName
                        }}
                        Buy {{
                            Amount
                            AmountInUSD
                            Account {{
                                Address
                            }}
                            Currency {{
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }}
                            Price
                        }}
                        Sell {{
                            Amount
                            AmountInUSD
                            Account {{
                                Address
                            }}
                            Currency {{
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }}
                            Price
                        }}
                        Market {{
                            MarketAddress
                        }}
                    }}
                    Transaction {{
                        Signature
                        Signer
                        Fee
                    }}
                }}
            }}
        }}
        """

    @staticmethod
    def track_trader_filtered(
        trader_address: str,
        mint_address: str = None,
        dex_name: str = None,
        min_amount_usd: float = None
    ) -> str:
        """Trackear trader con filtros opcionales - MÉTODO GENERAL ✅"""
        
        # Construir filtros adicionales
        additional_filters = []
        
        # Filtro de mint address
        if mint_address:
            additional_filters.append('''any: [
                {Buy: {Currency: {MintAddress: {is: "%s"}}}},
                {Sell: {Currency: {MintAddress: {is: "%s"}}}}
            ]''' % (mint_address, mint_address))
        
        # Filtro de DEX
        if dex_name:
            additional_filters.append('Dex: {ProtocolName: {is: "%s"}}' % dex_name)
        
        # Filtro de monto mínimo
        if min_amount_usd:
            additional_filters.append('''any: [
                {Buy: {AmountInUSD: {gt: %s}}},
                {Sell: {AmountInUSD: {gt: %s}}}
            ]''' % (min_amount_usd, min_amount_usd))
        
        # Construir where clause
        base_filter = """{
                    Transaction: {
                        Result: {Success: true},
                        Signer: {is: "%s"}
                    }""" % trader_address
        
        if additional_filters:
            where_clause = base_filter + ",\n                    " + ",\n                    ".join(additional_filters) + "\n                }"
        else:
            where_clause = base_filter + "\n                }"
        
        return """
        subscription TrackTraderFiltered {
            Solana {
                DEXTrades(
                    where: %s
                ) {
                    Block {
                        Time
                        Height
                        Slot
                    }
                    Trade {
                        Dex {
                            ProgramAddress
                            ProtocolFamily
                            ProtocolName
                        }
                        Buy {
                            Amount
                            AmountInUSD
                            Account {
                                Address
                            }
                            Currency {
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }
                            Price
                        }
                        Sell {
                            Amount
                            AmountInUSD
                            Account {
                                Address
                            }
                            Currency {
                                Name
                                Symbol
                                MintAddress
                                Decimals
                                Native
                            }
                            Price
                        }
                        Market {
                            MarketAddress
                        }
                    }
                    Transaction {
                        Signature
                        Signer
                        Fee
                    }
                }
            }
        }
        """ % where_clause 