# -*- coding: utf-8 -*-
"""
Parser para balances de tokens de Solana.
"""
from typing import Any, Dict, List

from logging_system import AppLogger
from ....models import TokenBalance, BalanceResponse


class BalanceParser:
    """Parser para convertir respuestas RPC de balances en objetos BalanceResponse."""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

    def parse_token_balances(self, response: Dict[str, Any], owner_pubkey: str) -> BalanceResponse:
        """Parsea la respuesta de getTokenAccountsByOwner y extrae balances.
        
        Args:
            response: Respuesta JSON del RPC getTokenAccountsByOwner
            owner_pubkey: Dirección del propietario de los tokens
            
        Returns:
            BalanceResponse con los tokens parseados
        """
        try:
            result = response.get("result", {})
            value = result.get("value", [])

            tokens: List[TokenBalance] = []

            for account_info in value:
                try:
                    account = account_info.get("account", {})
                    pubkey = account_info.get("pubkey", "")

                    parsed_data = account.get("data", {}).get("parsed", {})
                    token_info = parsed_data.get("info", {})

                    mint = token_info.get("mint", "")
                    token_amount = token_info.get("tokenAmount", {})

                    # Extraer información del token
                    amount = int(token_amount.get("amount", "0"))
                    decimals = token_amount.get("decimals", 0)
                    ui_amount = token_amount.get("uiAmount", 0.0) or 0.0
                    ui_amount_string = token_amount.get("uiAmountString", "0")
                    lamports = account.get("lamports", 0)

                    # Solo incluir tokens que tengan balance o información válida
                    if mint and pubkey:
                        token_balance: TokenBalance = TokenBalance(
                            pubkey=pubkey,
                            mint=mint,
                            amount=amount,
                            decimals=decimals,
                            ui_amount=ui_amount,
                            ui_amount_string=ui_amount_string,
                            lamports=lamports,
                        )
                        tokens.append(token_balance)

                except Exception as e:
                    self._logger.warning(f"Error parsing token account info: {e}")
                    # Continuar con el siguiente token si hay error parseando uno
                    continue

            return BalanceResponse(
                owner=owner_pubkey,
                tokens=tokens,
            )

        except Exception as e:
            self._logger.error(f"Error parsing token balances response: {e}")
            return BalanceResponse(owner=owner_pubkey)
