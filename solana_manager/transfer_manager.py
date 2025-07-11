# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional, Dict, Any
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey as PublicKey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
import asyncio


class SolanaTransfer:
    """Transferencias SOL - Versión asíncrona y moderna"""

    def __init__(self, network: str = 'mainnet-beta', rpc_url: str = 'https://api.mainnet-beta.solana.com'):
        self.network = network
        self.rpc_url = rpc_url
        self.client: Optional[AsyncClient] = None

    async def __aenter__(self):
        self.client = AsyncClient(self.rpc_url)
        is_connected = await self.client.is_connected()
        if is_connected:
            print(f"🌐 Conectado a Solana {self.network} (RPC: {self.rpc_url})")
        else:
            print(f"🔌 No se pudo conectar a Solana {self.network}. Por favor, verifica la RPC URL.")
            raise Exception("No se pudo conectar a la red Solana")

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.close()
            self.client = None

    async def transfer_sol(self, from_keypair: Keypair, to_address: str, amount_sol: float, max_retries: int = 3, initial_delay: int = 2) -> Optional[str]:
        """Transfiere SOL de forma asíncrona con reintentos y confirmación."""
        if not self.client:
            print("❌ Cliente no conectado. Llama a wallet_manager.connect() primero.")
            return None

        for attempt in range(max_retries):
            try:
                lamports = int(amount_sol * 1_000_000_000)
                print(f"🔄 Iniciando transferencia de {amount_sol} SOL (Intento {attempt + 1}/{max_retries})")

                to_pubkey = PublicKey.from_string(to_address)

                transfer_instruction = transfer(
                    TransferParams(
                        from_pubkey=from_keypair.pubkey(),
                        to_pubkey=to_pubkey,
                        lamports=lamports
                    )
                )

                recent_blockhash_response = await self.client.get_latest_blockhash()
                recent_blockhash = recent_blockhash_response.value.blockhash

                transaction = Transaction.new_signed_with_payer(
                    [transfer_instruction], 
                    from_keypair.pubkey(), 
                    [from_keypair], 
                    recent_blockhash
                )

                print("🔄 Enviando transacción a la red...")
                response = await self.client.send_transaction(transaction)
                signature = response.value
                
                print(f"✅ Transacción enviada. Signature: {signature}")
                await self.confirm_transaction(signature)

                print("🎉 ¡Transferencia confirmada exitosamente!")
                print(f"💰 Cantidad: {amount_sol} SOL")
                print(f"📍 Desde: {from_keypair.pubkey()}")
                print(f"📍 Hacia: {to_address}")
                print(f"🔗 Explorer: https://explorer.solana.com/tx/{signature}?cluster={self.network}")
                
                return str(signature)

            except Exception as e:
                print(f"❌ Error en intento {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⏳ Reintentando en {delay} segundos...")
                    await asyncio.sleep(delay)
                else:
                    print("❌ Transferencia fallida después de múltiples reintentos.")
                    return None
        return None

    async def confirm_transaction(self, signature: str, timeout: int = 60, delay: int = 2):
        """Confirma una transacción esperando su finalización."""
        print(f"⏳ Confirmando transacción {str(signature)[:30]}...")
        start_time = datetime.now()
        
        while (datetime.now() - start_time).total_seconds() < timeout:
            try:
                response = await self.client.get_signature_statuses([signature])
                if response.value and response.value[0] is not None:
                    status = response.value[0]
                    if status.confirmation_status in ('confirmed', 'finalized'):
                        print(f"✅ Transacción confirmada con estado: {status.confirmation_status}")
                        return
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"⚠️  Error durante confirmación: {e}")
                await asyncio.sleep(delay)
        
        print("⌛️ Timeout esperando confirmación de la transacción.")

    async def get_transfer_fee_estimate(self, amount_to_send: float, compute_units_limit: int = 200000, priority_fee_micro_lamports: int = 1) -> Dict[str, Any]:
        """
        Estima comisiones de transferencia de forma asíncrona.
        
        Args:
            amount_to_send: Cantidad de SOL a enviar
            compute_units_limit: Límite de unidades de cómputo (default: 200,000)
            priority_fee_micro_lamports: Precio por unidad de cómputo en micro-lamports (default: 1)
        """
        if not self.client:
            print("❌ Cliente no conectado.")
            return {}
        
        try:
            print("🔄 Calculando comisiones dinámicamente...")
            
            # Crear una transacción de ejemplo real para obtener el fee exacto
            from_keypair = Keypair()
            to_keypair = Keypair()
            
            # Crear instrucción de transferencia con la cantidad real
            lamports_to_send = int(amount_to_send * 1_000_000_000)
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=from_keypair.pubkey(),
                    to_pubkey=to_keypair.pubkey(),
                    lamports=lamports_to_send
                )
            )
            
            # Obtener el último blockhash para la transacción
            blockhash_response = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_response.value.blockhash
            
            # Crear transacción para calcular el fee
            transaction = Transaction.new_signed_with_payer(
                [transfer_instruction],
                from_keypair.pubkey(),
                [from_keypair],
                recent_blockhash
            )
            
            # Obtener fee usando get_fee_for_message con la transacción serializada
            fee_response = await self.client.get_fee_for_message(transaction.message)
            
            # Tarifa base: 5000 lamports por firma (según documentación de Solana)
            base_fee_lamports = 5000
            
            if fee_response.value is not None:
                # Si obtenemos un fee específico, usarlo como base
                total_fee_lamports = fee_response.value
                fee_source = 'dynamic_calculation'
            else:
                # Si no se puede obtener el fee específico, calcular manualmente
                print("⚠️ No se pudo obtener fee específico, calculando manualmente...")
                
                # Calcular tarifa de priorización
                priority_fee_lamports = (compute_units_limit * priority_fee_micro_lamports) / 1_000_000  # Convertir micro-lamports a lamports
                
                # Tarifa total = tarifa base + tarifa de priorización
                total_fee_lamports = base_fee_lamports + priority_fee_lamports
                fee_source = 'manual_calculation'
            
            # Convertir a SOL
            base_fee_sol = base_fee_lamports / 1_000_000_000
            total_fee_sol = total_fee_lamports / 1_000_000_000
            total_cost_sol = amount_to_send + total_fee_sol
            
            # Calcular tarifa de priorización (si aplica)
            priority_fee_lamports = total_fee_lamports - base_fee_lamports
            priority_fee_sol = priority_fee_lamports / 1_000_000_000
            
            # Obtener información adicional de la red
            slot_response = await self.client.get_slot()
            slot = slot_response.value if slot_response.value else 0
            
            # Obtener información del balance mínimo para rent exemption
            try:
                rent_response = await self.client.get_minimum_balance_for_rent_exemption(0)
                rent_exemption = rent_response.value if rent_response.value else 0
            except:
                rent_exemption = 2039280  # Valor estándar para rent exemption

            estimate = {
                'amount_sol': amount_to_send,
                'amount_lamports': lamports_to_send,
                'base_fee_lamports': base_fee_lamports,
                'base_fee_sol': base_fee_sol,
                'priority_fee_lamports': priority_fee_lamports,
                'priority_fee_sol': priority_fee_sol,
                'total_fee_lamports': total_fee_lamports,
                'total_fee_sol': total_fee_sol,
                'total_cost_sol': total_cost_sol,
                'compute_units_limit': compute_units_limit,
                'priority_fee_micro_lamports': priority_fee_micro_lamports,
                'network': self.network,
                'current_slot': slot,
                'rent_exemption_lamports': rent_exemption,
                'estimated_at': datetime.now().isoformat(),
                'fee_source': fee_source,
                'signatures_count': 1  # Una transferencia básica tiene 1 firma
            }

            print("💸 Estimación de comisiones:")
            print(f"   💰 Cantidad a enviar: {amount_to_send} SOL ({lamports_to_send:,} lamports)")
            print(f"   💳 Tarifa base: {base_fee_sol:.9f} SOL ({base_fee_lamports:,} lamports)")
            print(f"   ⚡ Tarifa priorización: {priority_fee_sol:.9f} SOL ({priority_fee_lamports:,} lamports)")
            print(f"   📊 Tarifa total: {total_fee_sol:.9f} SOL ({total_fee_lamports:,} lamports)")
            print(f"   💵 Costo total: {total_cost_sol:.9f} SOL")
            print(f"   🌐 Red: {self.network}")
            print(f"   📍 Slot actual: {slot:,}")
            print(f"   🔧 Fuente del fee: {estimate['fee_source']}")
            print(f"   ⚙️ Unidades cómputo: {compute_units_limit:,}")
            print(f"   🎯 Prioridad micro-lamports: {priority_fee_micro_lamports}")

            return estimate

        except Exception as e:
            print(f"❌ Error estimando comisiones: {e}")
            print("🔄 Intentando obtener fee mínimo de la red...")
            
            try:
                # Intentar obtener información básica de la red
                slot_response = await self.client.get_slot()
                slot = slot_response.value if slot_response.value else 0
                
                # Calcular tarifa manualmente como fallback
                base_fee_lamports = 5000
                priority_fee_lamports = (compute_units_limit * priority_fee_micro_lamports) / 1_000_000
                total_fee_lamports = base_fee_lamports + priority_fee_lamports
                
                base_fee_sol = base_fee_lamports / 1_000_000_000
                priority_fee_sol = priority_fee_lamports / 1_000_000_000
                total_fee_sol = total_fee_lamports / 1_000_000_000
                total_cost_sol = amount_to_send + total_fee_sol
                
                return {
                    'amount_sol': amount_to_send,
                    'amount_lamports': int(amount_to_send * 1_000_000_000),
                    'base_fee_lamports': base_fee_lamports,
                    'base_fee_sol': base_fee_sol,
                    'priority_fee_lamports': priority_fee_lamports,
                    'priority_fee_sol': priority_fee_sol,
                    'total_fee_lamports': total_fee_lamports,
                    'total_fee_sol': total_fee_sol,
                    'total_cost_sol': total_cost_sol,
                    'compute_units_limit': compute_units_limit,
                    'priority_fee_micro_lamports': priority_fee_micro_lamports,
                    'network': self.network,
                    'current_slot': slot,
                    'rent_exemption_lamports': 2039280,
                    'estimated_at': datetime.now().isoformat(),
                    'fee_source': 'fallback_manual',
                    'signatures_count': 1,
                    'error': str(e)
                }
                
            except Exception as fallback_error:
                print(f"❌ Error en fallback: {fallback_error}")
                
                # Último recurso: usar valores estándar
                base_fee_lamports = 5000
                priority_fee_lamports = 0
                total_fee_lamports = base_fee_lamports
                
                base_fee_sol = base_fee_lamports / 1_000_000_000
                priority_fee_sol = 0
                total_fee_sol = base_fee_sol
                total_cost_sol = amount_to_send + total_fee_sol
                
                return {
                    'amount_sol': amount_to_send,
                    'amount_lamports': int(amount_to_send * 1_000_000_000),
                    'base_fee_lamports': base_fee_lamports,
                    'base_fee_sol': base_fee_sol,
                    'priority_fee_lamports': priority_fee_lamports,
                    'priority_fee_sol': priority_fee_sol,
                    'total_fee_lamports': total_fee_lamports,
                    'total_fee_sol': total_fee_sol,
                    'total_cost_sol': total_cost_sol,
                    'compute_units_limit': compute_units_limit,
                    'priority_fee_micro_lamports': priority_fee_micro_lamports,
                    'network': self.network,
                    'current_slot': 0,
                    'rent_exemption_lamports': 2039280,
                    'estimated_at': datetime.now().isoformat(),
                    'fee_source': 'hardcoded_fallback',
                    'signatures_count': 1,
                    'error': f"Original: {e}, Fallback: {fallback_error}"
                }

    async def request_airdrop(self, public_key: str, amount_sol: float = 1.0) -> Optional[str]:
        """Solicita SOL gratis en devnet/testnet de forma asíncrona y confirma."""
        if not self.client:
            print("❌ Cliente no conectado.")
            return None
            
        if self.network not in ["devnet", "testnet"]:
            print("❌ Airdrop solo disponible en devnet/testnet")
            return None

        try:
            pubkey = PublicKey.from_string(public_key)
            lamports = int(amount_sol * 1_000_000_000)

            response = await self.client.request_airdrop(pubkey, lamports)
            signature = response.value

            if signature:
                print("🎁 Airdrop solicitado exitosamente!")
                print(f"💰 Cantidad: {amount_sol} SOL")
                print(f"📍 Wallet: {public_key}")
                print(f"🔗 Signature: {signature}")
                
                await self.confirm_transaction(str(signature))
                return str(signature)
            else:
                print("❌ Error solicitando airdrop, la red no retornó una firma.")
                return None

        except Exception as e:
            print(f"❌ Error en airdrop: {e}")
            return None
