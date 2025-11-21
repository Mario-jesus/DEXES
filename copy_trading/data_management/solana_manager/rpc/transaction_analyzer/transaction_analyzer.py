# -*- coding: utf-8 -*-
"""
Analiza las transacciones de Solana usando diferentes estrategias, para tokens que estan en la bonding curve,
AMM o Raydium.
"""
from typing import TypedDict, List, Optional, Set, TYPE_CHECKING

from logging_system import AppLogger
from ..utils import lamports_to_sol_str

if TYPE_CHECKING:
    from ..models import EnhancedTransactionResponse, AccountData, TokenTransfer


class TransactionAnalysis(TypedDict):
    side: str
    token_amount: str
    signer_native_balance_change: str
    pair_native_balance_change: str
    fee: str
    total_cost: str


class TransactionAnalyzer:
    """
    Analiza las transacciones de Solana usando diferentes estrategias, para tokens que estan en la bonding curve o
    en la AMM.
    """

    WSOL_MINT = "So11111111111111111111111111111111111111112"
    JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

    # Analiza una transacción de una operación de un token en la bonding
    def analyze_transaction_for_pump_fun(self, tx: 'EnhancedTransactionResponse', pair_address: Optional[str] = None) -> Optional['TransactionAnalysis']:
        try:
            if tx['type'] != "SWAP" or tx['source'] != "PUMP_FUN":
                self._logger.warning(f"Transaction {tx['signature']} is not a swap from PUMP_FUN")
                return None

            signer = tx['feePayer']
            token_transfers = tx['tokenTransfers']

            if not token_transfers:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfers")
                return None

            token_transfer = None
            for tt in token_transfers:
                if tt['mint'] != self.WSOL_MINT:
                    token_transfer = tt
                    break

            if token_transfer is None:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfer with a mint different from WSOL_MINT")
                return None

            signer_ata_address = token_transfer['toTokenAccount'] if token_transfer['toUserAccount'] == signer else token_transfer['fromTokenAccount']

            if pair_address is not None and pair_address not in [token_transfer['fromUserAccount'], token_transfer['toUserAccount']]:
                self._logger.warning(f"Transaction {tx['signature']} is a swap from Pump.fun with a token that is not the pair address {pair_address}")
                return None

            if signer not in [token_transfer['fromUserAccount'], token_transfer['toUserAccount']]:
                self._logger.warning(f"Transaction {tx['signature']} is a swap from Pump.fun with a fee payer that is not the fromUserAccount or toUserAccount")
                return None

            pair_address = pair_address or (token_transfer['toUserAccount'] if token_transfer['fromUserAccount'] == signer else token_transfer['fromUserAccount'])

            account_data = tx['accountData']

            if not account_data:
                self._logger.warning(f"Transaction {tx['signature']} has no account data")
                return None

            signer_account = None
            pair_account = None
            for account in account_data:
                if account['account'] == signer:
                    signer_account = account
                if account['account'] == pair_address:
                    pair_account = account

            if signer_account is None:
                self._logger.warning(f"Transaction {tx['signature']} has no account data for the signer {signer}")
                return None

            if pair_account is None:
                self._logger.warning(f"Transaction {tx['signature']} has no account data for the pair address {pair_address}")
                return None

            signer_native_balance_change = signer_account['nativeBalanceChange']
            pair_native_balance_change = pair_account['nativeBalanceChange']

            side = "buy" if token_transfer['toUserAccount'] == signer else "sell"
            total_cost = self._get_total_cost(account_data, {signer, pair_address, signer_ata_address})

            if total_cost is None:
                self._logger.warning(f"Transaction {tx['signature']} has no total cost for the signer {signer} and the pair address {pair_address} and the signer ATA address {signer_ata_address}")
                return None

            token_amount = token_transfer['tokenAmount'] if side == "buy" else -token_transfer['tokenAmount']

            return {
                'side': side,
                'token_amount': str(token_amount),
                'signer_native_balance_change': lamports_to_sol_str(signer_native_balance_change),
                'pair_native_balance_change': lamports_to_sol_str(pair_native_balance_change),
                'fee': lamports_to_sol_str(tx['fee']),
                'total_cost': lamports_to_sol_str(total_cost),
            }

        except Exception as e:
            self._logger.error(f"Error analyzing transaction {tx['signature']}: {e}")
            return None

    # Analiza una transacción de una operación de un token en la AMM
    def analyze_transaction_for_pump_amm(self, tx: 'EnhancedTransactionResponse', pair_address: Optional[str] = None) -> Optional['TransactionAnalysis']:
        try:
            if tx['type'] != "SWAP" or tx['source'] != "PUMP_AMM":
                self._logger.warning(f"Transaction {tx['signature']} is not a swap from PUMP_AMM")
                return None

            signer = tx['feePayer']
            token_transfers = tx['tokenTransfers']

            if not token_transfers:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfers")
                return None

            token_transfer_base = None
            for tt in token_transfers:
                if tt['mint'] != self.WSOL_MINT:
                    token_transfer_base = tt
                    break

            if token_transfer_base is None:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfer with a mint different from WSOL_MINT")
                return None

            signer_ata_address = token_transfer_base['toTokenAccount'] if token_transfer_base['toUserAccount'] == signer else token_transfer_base['fromTokenAccount']

            pair_address = pair_address or (token_transfer_base['toUserAccount'] if token_transfer_base['fromUserAccount'] == signer else token_transfer_base['fromUserAccount'])

            token_transfer_quote = None
            for tt in token_transfers:
                if tt['mint'] != self.WSOL_MINT:
                    continue

                if pair_address in [tt['fromUserAccount'], tt['toUserAccount']] and signer in [tt['fromUserAccount'], tt['toUserAccount']]:
                    token_transfer_quote = tt
                    break

            if token_transfer_quote is None:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfer with a mint different from WSOL_MINT and a pair address {pair_address} and a signer {signer}")
                return None

            pool_address = token_transfer_quote['fromTokenAccount'] if token_transfer_quote['fromUserAccount'] == pair_address else token_transfer_quote['toTokenAccount']

            account_data = tx['accountData']

            if not account_data:
                self._logger.warning(f"Transaction {tx['signature']} has no account data")
                return None

            signer_account = None
            pool_account = None
            for account in account_data:
                if account['account'] == pool_address:
                    pool_account = account
                if account['account'] == signer:
                    signer_account = account

            if pool_account is None:
                self._logger.warning(f"Transaction {tx['signature']} has no account data for the pool address {pool_address}")
                return None

            if signer_account is None:
                self._logger.warning(f"Transaction {tx['signature']} has no account data for the signer {signer}")
                return None

            pair_native_balance_change = pool_account['nativeBalanceChange']
            signer_native_balance_change = signer_account['nativeBalanceChange']

            side = "buy" if token_transfer_base['toUserAccount'] == signer else "sell"

            total_cost = self._get_total_cost(account_data, {signer, pool_address, signer_ata_address})

            if total_cost is None:
                self._logger.warning(f"Transaction {tx['signature']} has no total cost for the signer {signer} and the pair address {pair_address} and the signer ATA address {signer_ata_address}")
                return None

            token_amount = token_transfer_base['tokenAmount'] if side == "buy" else -token_transfer_base['tokenAmount']

            return {
                'side': side,
                'token_amount': str(token_amount),
                'signer_native_balance_change': lamports_to_sol_str(signer_native_balance_change),
                'pair_native_balance_change': lamports_to_sol_str(pair_native_balance_change),
                'fee': lamports_to_sol_str(tx['fee']),
                'total_cost': lamports_to_sol_str(total_cost),
            }

        except Exception as e:
            self._logger.error(f"Error analyzing transaction {tx['signature']}: {e}")
            return None

    def analyze_transaction_for_pump_amm_by_jupiter(self, tx: 'EnhancedTransactionResponse', pair_address: Optional[str] = None) -> Optional['TransactionAnalysis']:
        try:
            if tx['type'] != "SWAP":
                self._logger.warning(f"Transaction {tx['signature']} is not a swap")
                return None

            account_data = tx['accountData']
            is_jupiter_program_id = False
            for account in account_data:
                if account['account'] == self.JUPITER_PROGRAM_ID:
                    is_jupiter_program_id = True
                    break

            if not is_jupiter_program_id:
                self._logger.warning(f"Transaction {tx['signature']} is not a swap from Jupiter")
                return None

            signer1_address = tx['feePayer']
            signer2_address = None
            pair_address = None
            pool_address = None
            token_transfers = tx['tokenTransfers']

            from_users_accounts_for_ttbase = set()
            to_users_accounts_for_ttbase = set()
            from_users_accounts_for_ttquote = set()
            to_users_accounts_for_ttquote = set()
            token_transfer_base: List[TokenTransfer] = []
            token_transfer_quote = []
            for tt in token_transfers:
                if tt['mint'] != self.WSOL_MINT:
                    token_transfer_base.append(tt)
                    from_users_accounts_for_ttbase.add(tt['fromUserAccount'])
                    to_users_accounts_for_ttbase.add(tt['toUserAccount'])
                if tt['mint'] == self.WSOL_MINT:
                    token_transfer_quote.append(tt)
                    from_users_accounts_for_ttquote.add(tt['fromUserAccount'])
                    to_users_accounts_for_ttquote.add(tt['toUserAccount'])

            if not token_transfer_base:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfer with a mint different from WSOL_MINT for the signer {signer1_address}")
                return None

            account_data = tx['accountData']

            has_more_than_one_token_transfer_base = len(token_transfer_base) > 1
            if has_more_than_one_token_transfer_base:
                if len(from_users_accounts_for_ttbase) < len(to_users_accounts_for_ttbase):
                    signer2_address = from_users_accounts_for_ttbase.pop()
                else:   
                    signer2_address = to_users_accounts_for_ttbase.pop()

                if len(from_users_accounts_for_ttquote) < len(to_users_accounts_for_ttquote):
                    pair_address = from_users_accounts_for_ttquote.pop()
                elif len(from_users_accounts_for_ttquote) == len(to_users_accounts_for_ttquote):
                    first_address_for_from_users = from_users_accounts_for_ttquote.pop()
                    first_address_for_to_users = to_users_accounts_for_ttquote.pop()
                    if first_address_for_from_users == signer2_address:
                        pair_address = first_address_for_to_users
                    else:
                        pair_address = first_address_for_from_users
                else:
                    pair_address = to_users_accounts_for_ttquote.pop()

                if signer2_address == pair_address:
                    self._logger.warning(f"Transaction {tx['signature']} has a signer2 address {signer2_address} that is the same as the pair address {pair_address}")
                    return None
            else:
                from_user_account_address = token_transfer_base[0]['fromUserAccount']
                to_user_account_address = token_transfer_base[0]['toUserAccount']

                for account in account_data:
                    if account['account'] == from_user_account_address and account['nativeBalanceChange'] != 0:
                        signer2_address = from_user_account_address
                        pair_address = to_user_account_address
                        break
                    if account['account'] == to_user_account_address and account['nativeBalanceChange'] != 0:
                        signer2_address = to_user_account_address
                        pair_address = from_user_account_address
                        break

                if signer2_address is None:
                    self._logger.warning(f"Transaction {tx['signature']} has no signer2 address for the from user account address {from_user_account_address} and the to user account address {to_user_account_address}")
                    return None

                if pair_address is None:
                    self._logger.warning(f"Transaction {tx['signature']} has no pair address for the from user account address {from_user_account_address} and the to user account address {to_user_account_address}")
                    return None

            for tt in token_transfer_quote:
                if tt['fromUserAccount'] == pair_address:
                    pool_address = tt['fromTokenAccount']
                    break
                if tt['toUserAccount'] == pair_address:
                    pool_address = tt['toTokenAccount']
                    break

            if pool_address is None:
                self._logger.warning(f"Transaction {tx['signature']} has no pool address for the pair address {pair_address}")
                return None

            signer_native_balance_change = 0
            pair_native_balance_change = 0
            for account in account_data:
                if account['account'] == signer2_address:
                    signer_native_balance_change += account['nativeBalanceChange']
                if account['account'] == pool_address:
                    pair_native_balance_change += account['nativeBalanceChange']

            token_transfer_base_with_pair_address = None
            for tt in token_transfer_base:
                if pair_address in [tt['fromUserAccount'], tt['toUserAccount']] and signer2_address in [tt['fromUserAccount'], tt['toUserAccount']]:
                    token_transfer_base_with_pair_address = tt
                    break

            if token_transfer_base_with_pair_address is None:
                self._logger.warning(f"Transaction {tx['signature']} has no token transfer with a pair address {pair_address} and a signer2 address {signer2_address}")
                return None

            side = "buy" if token_transfer_base_with_pair_address['toUserAccount'] == signer2_address else "sell"

            total_cost = self._get_total_cost(account_data, {signer2_address, pool_address})

            if total_cost is None:
                self._logger.warning(f"Transaction {tx['signature']} has no total cost for the signer1 address {signer1_address} and the signer2 address {signer2_address} and the pool address {pool_address}")
                return None

            token_amount = 0
            for tt in token_transfer_base:
                token_amount += tt['tokenAmount'] if side == "buy" else -tt['tokenAmount']

            return {
                'side': side,
                'token_amount': str(token_amount),
                'signer_native_balance_change': lamports_to_sol_str(signer_native_balance_change),
                'pair_native_balance_change': lamports_to_sol_str(pair_native_balance_change),
                'fee': lamports_to_sol_str(tx['fee']),
                'total_cost': lamports_to_sol_str(total_cost),
            }

        except Exception as e:
            self._logger.error(f"Error analyzing transaction {tx['signature']}: {e}")
            return None

    def is_pump_amm_of_jupiter(self, tx: 'EnhancedTransactionResponse') -> bool:
        try:
            if tx['type'] != "SWAP":
                return False

            account_data = tx['accountData']
            is_jupiter_program_id = False
            for account in account_data:
                if account['account'] == self.JUPITER_PROGRAM_ID:
                    is_jupiter_program_id = True
                    break

            return is_jupiter_program_id
        except Exception as e:
            self._logger.error(f"Error detecting if transaction {tx['signature']} is a pump AMM of Jupiter: {e}")
            return False

    def _get_total_cost(self, account_data: List['AccountData'], exclude_pubkeys: Set[str]) -> Optional[int]:
        try:
            total_cost = 0
            for account in account_data:
                if account['account'] in exclude_pubkeys:
                    continue
                total_cost += abs(account['nativeBalanceChange'])
            return total_cost
        except Exception as e:
            self._logger.error(f"Error getting total cost: {e}")
            return None
