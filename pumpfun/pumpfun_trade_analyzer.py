# -*- coding: utf-8 -*-
"""
Pump.fun Trade Analyzer - Analizador asíncrono especializado para trades de Pump.fun
Con análisis detallado de todos los componentes de la transacción
"""
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging

from solana.rpc.async_api import AsyncClient as SolanaAsyncClient
from solders.signature import Signature


def serialize_for_json(obj: Any) -> Any:
    """
    Serializa un objeto para JSON, manejando tipos especiales como Pubkey.
    
    Args:
        obj: Objeto a serializar
        
    Returns:
        Objeto serializable para JSON
    """
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return format(obj, "f")
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    elif hasattr(obj, 'to_dict'):
        return serialize_for_json(obj.to_dict())
    elif hasattr(obj, '__dict__'):
        # Para objetos que tienen __dict__ pero no to_dict
        return serialize_for_json(obj.__dict__)
    elif hasattr(obj, 'pubkey'):
        # Para objetos Pubkey de Solana
        return str(obj.pubkey)
    else:
        # Intentar convertir a string como último recurso
        try:
            return str(obj)
        except:
            return f"<non-serializable: {type(obj).__name__}>"


@dataclass
class TokenBalanceInfo:
    """Información detallada del balance de un token"""
    account_index: int
    mint: str
    amount: Decimal
    ui_amount: float
    decimals: int
    owner: Optional[str]
    program_id: Optional[str]

    def __str__(self):
        return f"""
Token Balance:
  Mint: {self.mint}
  Amount: {self.ui_amount:,.6f} (raw: {self.amount})
  Decimals: {self.decimals}
  Owner: {self.owner or 'Unknown'}
  Program: {self.program_id or 'Unknown'}
  Account Index: {self.account_index}
"""

@dataclass
class InstructionAnalysis:
    """Información detallada de una instrucción"""
    program: str
    program_id: str
    instruction_type: str
    accounts: List[str]
    data: Dict[str, Any]
    stack_height: Optional[int]

    def __str__(self):
        return f"""
Instruction Detail:
  Program: {self.program}
  Program ID: {self.program_id}
  Type: {self.instruction_type}
  Stack Height: {self.stack_height or 'N/A'}
  Accounts: {', '.join(self.accounts)}
  Data: {self.data}
"""

@dataclass
class BalanceChangeInfo:
    """Cambio en el balance de una cuenta"""
    account: str
    pre_balance: int
    post_balance: int
    change: int
    change_in_sol: float

    def __str__(self):
        return f"""
Balance Change for {self.account}:
  Pre: {self.pre_balance:,} lamports ({self.pre_balance/1e9:.9f} SOL)
  Post: {self.post_balance:,} lamports ({self.post_balance/1e9:.9f} SOL)
  Change: {self.change:,} lamports ({self.change_in_sol:,.9f} SOL)
"""

@dataclass
class TradeAnalysisResult:
    """Información ultra detallada de un trade en Pump.fun"""
    # Información básica
    signature: str
    slot: int
    block_time: Optional[int]
    timestamp: datetime
    recent_blockhash: str  # Nuevo campo
    
    # Estado de la transacción
    success: bool
    error: Optional[str]
    fee: int
    fee_in_sol: float
    compute_units_consumed: Optional[int]
    compute_budget_instructions: List[Dict[str, Any]]  # Nuevo campo
    
    # Tipo de operación
    trade_type: str
    operation_description: str
    
    # Participantes principales
    trader: str
    token_mint: str
    token_program: str  # Nuevo campo
    
    # Cantidades
    token_amount: float
    sol_amount: float
    
    # Balances detallados
    balance_changes: List[BalanceChangeInfo]
    token_balances_pre: List[TokenBalanceInfo]
    token_balances_post: List[TokenBalanceInfo]
    
    # Instrucciones y logs
    instructions: List[InstructionAnalysis]
    inner_instructions: List[List[InstructionAnalysis]]
    log_messages: List[str]
    
    # Análisis de costos
    total_cost_breakdown: Dict[str, float]
    
    # Información de cuentas
    account_roles: Dict[str, List[str]]  # Nuevo campo: mapea cuentas a sus roles
    program_invocations: Dict[str, int]  # Nuevo campo: cuenta cuántas veces se invoca cada programa
    
    def __str__(self):
        return f"""
=== PUMP.FUN DETAILED TRADE ANALYSIS ===

BASIC INFORMATION:
Signature: {self.signature}
Slot: {self.slot}
Block Time: {self.block_time}
Timestamp: {self.timestamp}
Recent Blockhash: {self.recent_blockhash}

TRANSACTION STATUS:
Success: {self.success}
Error: {self.error or 'None'}
Fee: {self.fee:,} lamports ({self.fee_in_sol:.9f} SOL)
Compute Units: {self.compute_units_consumed or 'Unknown'}

COMPUTE BUDGET INSTRUCTIONS:
{self._format_compute_budget()}

TRADE DETAILS:
Type: {self.trade_type.upper()}
Description: {self.operation_description}
Trader: {self.trader}
Token: {self.token_mint}
Token Program: {self.token_program}
Token Amount: {self.token_amount:,.6f}
SOL Amount: {self.sol_amount:.9f}

COST BREAKDOWN:
{self._format_cost_breakdown()}

BALANCE CHANGES:
{self._format_balance_changes()}

TOKEN BALANCES:
{self._format_token_balances()}

ACCOUNT ROLES:
{self._format_account_roles()}

PROGRAM INVOCATIONS:
{self._format_program_invocations()}

INSTRUCTIONS SUMMARY:
{self._format_instructions_summary()}

LOG MESSAGES:
{self._format_log_messages()}
"""

    def _format_cost_breakdown(self) -> str:
        result = []
        for cost_type, amount in self.total_cost_breakdown.items():
            result.append(f"  {cost_type}: {amount:.9f} SOL")
        return "\n".join(result)

    def _format_balance_changes(self) -> str:
        return "\n".join(str(change) for change in self.balance_changes)

    def _format_token_balances(self) -> str:
        pre = "\nPRE-TRANSACTION:"
        pre += "\n".join(str(balance) for balance in self.token_balances_pre)
        post = "\nPOST-TRANSACTION:"
        post += "\n".join(str(balance) for balance in self.token_balances_post)
        return f"{pre}\n{post}"

    def _format_instructions_summary(self) -> str:
        result = []
        for i, inst in enumerate(self.instructions):
            result.append(f"\nInstruction {i+1}:")
            result.append(str(inst))
            if i < len(self.inner_instructions):
                result.append("  Inner Instructions:")
                for inner in self.inner_instructions[i]:
                    result.append(f"    {str(inner)}")
        return "\n".join(result)

    def _format_log_messages(self) -> str:
        return "\n".join(f"  {msg}" for msg in self.log_messages)

    def _format_compute_budget(self) -> str:
        result = []
        for inst in self.compute_budget_instructions:
            result.append(f"  {inst.get('description', 'Unknown compute budget instruction')}")
        return "\n".join(result) if result else "  No compute budget instructions found"

    def _format_account_roles(self) -> str:
        result = []
        for account, roles in self.account_roles.items():
            result.append(f"  {account}:")
            for role in roles:
                result.append(f"    - {role}")
        return "\n".join(result)

    def _format_program_invocations(self) -> str:
        result = []
        for program, count in self.program_invocations.items():
            result.append(f"  {program}: {count} invocation(s)")
        return "\n".join(result)

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la información detallada del trade a diccionario"""
        base_dict = {
            'signature': self.signature,
            'slot': self.slot,
            'block_time': self.block_time,
            'timestamp': self.timestamp.isoformat(),
            'recent_blockhash': self.recent_blockhash,
            'success': self.success,
            'error': self.error,
            'fee': self.fee,
            'fee_in_sol': self.fee_in_sol,
            'compute_units_consumed': self.compute_units_consumed,
            'compute_budget_instructions': self.compute_budget_instructions,
            'trade_type': self.trade_type,
            'operation_description': self.operation_description,
            'trader': self.trader,
            'token_mint': self.token_mint,
            'token_program': self.token_program,
            'token_amount': self.token_amount,
            'sol_amount': self.sol_amount,
            'balance_changes': serialize_for_json(self.balance_changes),
            'token_balances_pre': serialize_for_json(self.token_balances_pre),
            'token_balances_post': serialize_for_json(self.token_balances_post),
            'instructions': serialize_for_json(self.instructions),
            'inner_instructions': serialize_for_json(self.inner_instructions),
            'log_messages': self.log_messages,
            'total_cost_breakdown': self.total_cost_breakdown,
            'account_roles': self.account_roles,
            'program_invocations': self.program_invocations
        }
        return base_dict


class PumpFunTradeAnalyzer:
    """Analizador asíncrono especializado para trades de Pump.fun con análisis detallado"""

    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com", logger: Optional[logging.Logger] = None):
        """
        Inicializa el analizador de trades
        
        Args:
            rpc_url: URL del RPC de Solana
        """
        self.rpc_url = rpc_url
        self.solana_client = SolanaAsyncClient(self.rpc_url)
        self.logger = logger or logging.getLogger(__name__)
        self.logger.debug("🔍 Pump.fun Trade Analyzer inicializado")
        self.logger.info(f"🌐 Configurado para conectar a {self.rpc_url}")

    async def __aenter__(self):
        self.logger.debug("Iniciando sesión de Trade Analyzer...")
        await self.solana_client.__aenter__()
        self.logger.debug("Sesión de Solana AsyncClient iniciada en Trade Analyzer.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.logger.debug("Cerrando sesión de Trade Analyzer...")
        await self.solana_client.__aexit__(exc_type, exc_val, exc_tb)
        self.logger.debug("Sesión de Solana AsyncClient cerrada en Trade Analyzer.")

    async def test_connection(self) -> bool:
        """Prueba la conexión al RPC de Solana"""
        try:
            response = await self.solana_client.get_slot()
            if response.value:
                self.logger.info(f"✅ Conexión RPC exitosa - Slot actual: {response.value}")
                return True
            else:
                self.logger.error("❌ No se pudo obtener el slot actual")
                return False
        except Exception as e:
            self.logger.error(f"❌ Error probando conexión RPC: {e}")
            return False

    async def get_transaction(self, signature: str) -> Optional[Any]:
        """Obtiene una transacción desde la blockchain"""
        try:
            sig_obj = Signature.from_string(signature)
            
            response = await self.solana_client.get_transaction(
                sig_obj,
                encoding="jsonParsed",
                max_supported_transaction_version=0
            )

            if response.value:
                self.logger.info(f"✅ Transacción obtenida: {signature[:8]}...")
                return response.value
            else:
                self.logger.error(f"❌ No se encontró la transacción: {signature}")
                return None

        except Exception as e:
            self.logger.error(f"❌ Error obteniendo transacción: {e}")
            return None

    def _parse_token_balance(self, balance_data: Dict[str, Any]) -> TokenBalanceInfo:
        """Parsea la información de balance de un token"""
        # Acceder directamente a los atributos del objeto UiTransactionTokenBalance
        account_index = getattr(balance_data, 'account_index', 0)
        mint = getattr(balance_data, 'mint', 'Unknown')
        ui_token_amount = getattr(balance_data, 'ui_token_amount', None)
        owner = getattr(balance_data, 'owner', None)
        program_id = getattr(balance_data, 'program_id', None)

        # Extraer información del ui_token_amount
        if ui_token_amount:
            amount = Decimal(getattr(ui_token_amount, 'amount', '0'))
            ui_amount = float(getattr(ui_token_amount, 'ui_amount', 0.0) or 0.0)
            decimals = getattr(ui_token_amount, 'decimals', 0)
        else:
            amount = Decimal('0')
            ui_amount = 0.0
            decimals = 0

        # Si owner o program_id son Some(value), extraer el valor
        if isinstance(owner, dict) and 'Some' in owner:
            owner = owner['Some']
        if isinstance(program_id, dict) and 'Some' in program_id:
            program_id = program_id['Some']

        # Convertir Pubkey a string si es necesario
        if hasattr(program_id, '__str__'):
            program_id = str(program_id)
        if hasattr(owner, '__str__'):
            owner = str(owner)
        if hasattr(mint, '__str__'):
            mint = str(mint)

        return TokenBalanceInfo(
            account_index=account_index,
            mint=mint,
            amount=amount,
            ui_amount=ui_amount,
            decimals=decimals,
            owner=owner,
            program_id=program_id
        )

    def _parse_instruction(self, inst_data: Dict[str, Any]) -> InstructionAnalysis:
        """Parsea la información de una instrucción"""
        # Extraer programa y program_id
        program = getattr(inst_data, 'program', None) or inst_data.get('program', 'Unknown')
        program_id = getattr(inst_data, 'program_id', None) or inst_data.get('program_id', 'Unknown')
        
        # Extraer tipo de instrucción y datos
        parsed = getattr(inst_data, 'parsed', None) or inst_data.get('parsed', {})
        if isinstance(parsed, dict):
            inst_type = parsed.get('type', 'Unknown')
            inst_info = parsed.get('info', {})
        else:
            inst_type = getattr(parsed, 'type', 'Unknown')
            inst_info = getattr(parsed, 'info', {})
        
        # Extraer cuentas involucradas
        accounts = []
        if hasattr(inst_data, 'accounts'):
            accounts = inst_data.accounts
        elif isinstance(inst_data, dict) and 'accounts' in inst_data:
            accounts = inst_data['accounts']
        elif inst_info:
            # Extraer cuentas de la información parseada
            if isinstance(inst_info, dict):
                for key, value in inst_info.items():
                    if isinstance(value, str) and len(value) > 30:
                        accounts.append(value)

        # Extraer stack height
        stack_height = getattr(inst_data, 'stack_height', None)
        if isinstance(stack_height, dict) and 'Some' in stack_height:
            stack_height = stack_height['Some']

        return InstructionAnalysis(
            program=program,
            program_id=program_id,
            instruction_type=inst_type,
            accounts=accounts,
            data=inst_info,
            stack_height=stack_height
        )

    def _calculate_balance_changes(
        self,
        pre_balances: List[int],
        post_balances: List[int],
        account_keys: List[str]
    ) -> List[BalanceChangeInfo]:
        """Calcula los cambios en balances para todas las cuentas"""
        changes = []
        for i, (pre, post) in enumerate(zip(pre_balances, post_balances)):
            if i < len(account_keys):
                change = post - pre
                changes.append(BalanceChangeInfo(
                    account=account_keys[i],
                    pre_balance=pre,
                    post_balance=post,
                    change=change,
                    change_in_sol=change / 1e9
                ))
        return changes

    def _analyze_costs(
        self,
        balance_changes: List[BalanceChangeInfo],
        fee: int
    ) -> Dict[str, float]:
        """Analiza y desglosa los costos de la transacción"""
        breakdown = {
            'transaction_fee': fee / 1e9,  # Comisión base de Solana
            'protocol_fees': 0.0,          # Comisiones del protocolo
            'other_transfers': 0.0         # Otras transferencias
        }

        for change in balance_changes:
            if change.change < 0:  # Solo consideramos gastos
                abs_change = abs(change.change)
                if abs_change == fee:
                    continue  # Ya contabilizado como transaction_fee
                elif abs_change <= 10000:  # Comisiones típicas del protocolo
                    breakdown['protocol_fees'] += abs_change / 1e9
                else:
                    breakdown['other_transfers'] += abs_change / 1e9

        # El costo total es la suma de todas las transferencias negativas
        # No incluimos el fee dos veces
        breakdown['total_cost'] = abs(sum(
            change.change for change in balance_changes 
            if change.change < 0
        )) / 1e9

        return breakdown

    def _determine_operation_type(self, logs: List[str], instructions: List[InstructionAnalysis]) -> Tuple[str, str]:
        """Determina el tipo de operación y genera una descripción"""
        trade_type = "unknown"
        description = "Unknown operation"

        # Analizar logs
        for log in logs:
            if "Instruction: Buy" in log:
                trade_type = "buy"
                description = "Token purchase on Pump.fun"
                break
            elif "Instruction: Sell" in log:
                trade_type = "sell"
                description = "Token sale on Pump.fun"
                break

        # Analizar instrucciones si los logs no fueron conclusivos
        if trade_type == "unknown":
            for inst in instructions:
                if "buy" in inst.instruction_type.lower():
                    trade_type = "buy"
                    description = "Token purchase operation"
                    break
                elif "sell" in inst.instruction_type.lower():
                    trade_type = "sell"
                    description = "Token sale operation"
                    break

        return trade_type, description

    async def analyze_transaction(self, tx_data: Any) -> Optional[TradeAnalysisResult]:
        """Analiza una transacción de Pump.fun con análisis detallado"""
        try:
            # Extraer datos básicos
            slot = tx_data.slot
            block_time = getattr(tx_data, 'block_time', None)
            if isinstance(block_time, dict) and 'Some' in block_time:
                block_time = block_time['Some']
            timestamp = datetime.fromtimestamp(block_time) if block_time else datetime.now()

            # Extraer metadata
            transaction = getattr(tx_data, 'transaction', None)
            if hasattr(transaction, 'meta'):
                meta = transaction.meta
            elif isinstance(transaction, dict) and 'meta' in transaction:
                meta = transaction['meta']
            else:
                return None

            if not meta:
                return None

            # Estado y costos básicos
            success = meta.err is None
            error = str(meta.err) if meta.err else None
            fee = meta.fee
            compute_units = getattr(meta, 'compute_units_consumed', None)
            if isinstance(compute_units, dict) and 'Some' in compute_units:
                compute_units = compute_units['Some']

            # Extraer mensaje de la transacción
            message = transaction.transaction.message
            account_keys = []
            account_roles = {}
            program_invocations = {}
            
            # Manejar diferentes formatos de account_keys y extraer roles
            if hasattr(message, 'account_keys'):
                for key in message.account_keys:
                    pubkey = str(key.pubkey) if hasattr(key, 'pubkey') else str(key)
                    account_keys.append(pubkey)
                    
                    # Inicializar roles para esta cuenta
                    roles = []
                    if hasattr(key, 'signer') and key.signer:
                        roles.append('signer')
                    if hasattr(key, 'writable') and key.writable:
                        roles.append('writable')
                    if hasattr(key, 'source'):
                        roles.append(f"source: {key.source}")
                    
                    account_roles[pubkey] = roles

            # Analizar instrucciones de compute budget
            compute_budget_instructions = []
            if hasattr(message, 'instructions'):
                for inst in message.instructions:
                    if hasattr(inst, 'program_id') and str(inst.program_id) == "ComputeBudget111111111111111111111111111111":
                        desc = "Set compute unit limit" if "Fx9hNo" in str(inst.data) else "Set compute unit price"
                        compute_budget_instructions.append({
                            'program_id': str(inst.program_id),
                            'description': desc,
                            'data': str(inst.data)
                        })

            # Encontrar el trader (primer signer)
            trader = None
            for i, key in enumerate(message.account_keys):
                if hasattr(key, 'signer') and key.signer:
                    trader = str(key.pubkey)
                    break

            # Parsear instrucciones principales y contar invocaciones de programas
            instructions = []
            inner_instructions = []
            
            # Procesar instrucciones principales
            for inst in getattr(message, 'instructions', []):
                if hasattr(inst, 'parsed'):
                    parsed_inst = self._parse_instruction(inst.parsed)
                    instructions.append(parsed_inst)
                    
                    # Contar invocación del programa
                    program_id = str(parsed_inst.program_id)
                    program_invocations[program_id] = program_invocations.get(program_id, 0) + 1

            # Procesar instrucciones internas y contar invocaciones
            for inner_inst_group in getattr(meta, 'inner_instructions', []):
                inner_group = []
                for inner in inner_inst_group.instructions:
                    if hasattr(inner, 'parsed'):
                        parsed_inner = self._parse_instruction(inner.parsed)
                        inner_group.append(parsed_inner)
                        
                        # Contar invocación del programa
                        program_id = str(parsed_inner.program_id)
                        program_invocations[program_id] = program_invocations.get(program_id, 0) + 1
                
                inner_instructions.append(inner_group)

            # Analizar balances
            balance_changes = self._calculate_balance_changes(
                meta.pre_balances,
                meta.post_balances,
                account_keys
            )

            # Parsear balances de tokens y encontrar el token program
            token_balances_pre = []
            token_program = "Unknown"
            if hasattr(meta, 'pre_token_balances'):
                token_balances_pre = [
                    self._parse_token_balance(balance) 
                    for balance in meta.pre_token_balances
                ]
                # Extraer token program del primer balance
                if token_balances_pre:
                    token_program = token_balances_pre[0].program_id or "Unknown"

            token_balances_post = []
            if hasattr(meta, 'post_token_balances'):
                token_balances_post = [
                    self._parse_token_balance(balance) 
                    for balance in meta.post_token_balances
                ]

            # Determinar tipo de operación
            trade_type, operation_description = self._determine_operation_type(
                meta.log_messages or [],
                instructions
            )

            # Extraer información de tokens
            token_mint = "Unknown"
            token_amount = 0.0
            if token_balances_pre and token_balances_post:
                # Buscar balances de token SPL cuyo owner coincida con el trader
                trader_pre = next((tb for tb in token_balances_pre if str(tb.owner) == trader), None)
                trader_post = next((tb for tb in token_balances_post if str(tb.owner) == trader), None)
                if trader_pre and trader_post:
                    token_mint = str(trader_pre.mint)
                    token_amount = abs(trader_post.ui_amount - trader_pre.ui_amount)
                elif trader_post:
                    token_mint = str(trader_post.mint)
                    token_amount = trader_post.ui_amount
                elif trader_pre:
                    token_mint = str(trader_pre.mint)
                    token_amount = trader_pre.ui_amount

            # Calcular cantidad de SOL gastado (cambio neto en la cuenta del trader)
            sol_amount = 0.0
            for change in balance_changes:
                if change.account == trader:
                    sol_amount = abs(change.change) / 1e9
                    break

            # Analizar costos
            cost_breakdown = self._analyze_costs(balance_changes, fee)

            # Actualizar roles de cuenta basado en las instrucciones
            for inst in instructions + [inner for group in inner_instructions for inner in group]:
                for account in inst.accounts:
                    if account in account_roles:
                        role = f"used_in_{inst.program}_{inst.instruction_type}"
                        if role not in account_roles[account]:
                            account_roles[account].append(role)

            return TradeAnalysisResult(
                # Información básica
                signature=str(transaction.transaction.signatures[0]),
                slot=slot,
                block_time=block_time,
                timestamp=timestamp,
                recent_blockhash=str(transaction.transaction.message.recent_blockhash),
                
                # Estado
                success=success,
                error=error,
                fee=fee,
                fee_in_sol=fee / 1e9,
                compute_units_consumed=compute_units,
                compute_budget_instructions=compute_budget_instructions,
                
                # Detalles del trade
                trade_type=trade_type,
                operation_description=operation_description,
                trader=trader or "Unknown",
                token_mint=token_mint,
                token_program=token_program,
                token_amount=token_amount,
                sol_amount=sol_amount,
                
                # Balances
                balance_changes=balance_changes,
                token_balances_pre=token_balances_pre,
                token_balances_post=token_balances_post,
                
                # Instrucciones y logs
                instructions=instructions,
                inner_instructions=inner_instructions,
                log_messages=meta.log_messages or [],
                
                # Análisis de costos
                total_cost_breakdown=cost_breakdown,
                
                # Información de cuentas
                account_roles=account_roles,
                program_invocations=program_invocations
            )

        except Exception as e:
            self.logger.error(f"❌ Error analizando transacción: {e}")
            return None

    async def analyze_transaction_by_signature(self, signature: str) -> Optional[TradeAnalysisResult]:
        """Obtiene y analiza una transacción por su firma con análisis detallado"""
        try:
            # Obtener la transacción
            tx_data = await self.get_transaction(signature)
            if not tx_data:
                return None

            # Analizar la transacción
            return await self.analyze_transaction(tx_data)

        except Exception as e:
            self.logger.error(f"❌ Error analizando transacción por firma: {e}")
            return None

    async def analyze_multiple_transactions(
        self,
        signatures: List[str]
    ) -> Dict[str, Optional[TradeAnalysisResult]]:
        """Analiza múltiples transacciones de forma concurrente"""
        results = {}

        try:
            # Crear tareas para procesar transacciones concurrentemente
            tasks = [self.analyze_transaction_by_signature(signature) for signature in signatures]

            # Ejecutar todas las tareas al mismo tiempo
            trade_infos = await asyncio.gather(*tasks, return_exceptions=True)

            for signature, trade_info in zip(signatures, trade_infos):
                if isinstance(trade_info, Exception):
                    self.logger.error(f"❌ Error procesando transacción {signature}: {trade_info}")
                    results[signature] = None
                else:
                    results[signature] = trade_info

            return results

        except Exception as e:
            self.logger.error(f"❌ Error procesando múltiples transacciones: {e}")
            return results


# ============================================================================
# EJEMPLO DE USO
# ============================================================================

async def example_usage():
    """Ejemplo de uso del PumpFunTradeAnalyzer"""
    print("🚀 Ejemplo de uso del PumpFunTradeAnalyzer")
    print("=" * 60)

    # Firma de ejemplo (reemplazar con una firma real)
    example_signature = "5mzH9SMCHm5RYkTL1TxrrEqi3oxdtEuLXbkTMrZihYzhihTGN1w7AqXXv5pgCirrLEHuPAoreKcSsoGXs15BSJCS"

    # Usar async with para gestión automática de conexiones
    async with PumpFunTradeAnalyzer() as analyzer:
        # Verificar conexión
        print("\n📡 Verificando conexión RPC...")
        if not await analyzer.test_connection():
            print("❌ No se pudo conectar al RPC")
            return

        # Analizar una transacción individual
        print(f"\n🔍 Analizando transacción: {example_signature[:8]}...")
        trade_info = await analyzer.analyze_transaction_by_signature(example_signature)

        if trade_info:
            print("✅ Transacción analizada exitosamente:")
            print(trade_info)
            
            # También podemos obtener la información como diccionario
            trade_dict = trade_info.to_dict()
            print("\n📊 Información como diccionario:")
            print(trade_dict)
        else:
            print("❌ No se pudo analizar la transacción")


if __name__ == "__main__":
    # Ejecutar ejemplo
    asyncio.run(example_usage()) 