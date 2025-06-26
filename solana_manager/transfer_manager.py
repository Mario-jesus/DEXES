# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional, Dict, Any
from solders.keypair import Keypair
from solders.pubkey import Pubkey as PublicKey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
import base58

from .wallet_manager import SolanaWalletManager


class SolanaTransfer:
    """Transferencias SOL - Versión corregida que funciona con la API moderna"""
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        self.wallet_manager = wallet_manager
        self.client = wallet_manager.client

    def transfer_sol(self, from_keypair: Keypair, to_address: str, amount_sol: float) -> Optional[str]:
        """Transfiere SOL usando el patrón correcto de solders"""
        try:
            lamports = int(amount_sol * 1_000_000_000)
            print(f"🔄 Iniciando transferencia de {amount_sol} SOL ({lamports:,} lamports)")

            # 1. Validar dirección destino
            decoded = base58.b58decode(to_address)
            if len(decoded) != 32:
                print("❌ Dirección destino inválida: debe tener 32 bytes")
                return None

            to_pubkey = PublicKey.from_bytes(decoded)
            print(f"✅ Dirección destino validada: {to_address[:20]}...")

            # 2. Crear instrucción de transferencia
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=from_keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            print("✅ Instrucción de transferencia creada")

            # 3. Obtener blockhash reciente
            print("🔄 Obteniendo blockhash reciente...")
            recent_blockhash_response = self.client.get_latest_blockhash()
            if not recent_blockhash_response.value:
                print("❌ No se pudo obtener blockhash reciente")
                return None
            
            recent_blockhash = recent_blockhash_response.value.blockhash
            print(f"✅ Blockhash obtenido: {str(recent_blockhash)[:20]}...")

            # 4. SOLUCIÓN FINAL: Usar el patrón correcto de la documentación
            print("🔄 Creando transacción con patrón oficial...")
            
            try:
                # Patrón oficial de solders: Transaction([keypairs], message, blockhash)
                from solders.message import Message
                
                # Crear mensaje
                message = Message([transfer_instruction], from_keypair.pubkey())
                
                # Crear transacción con el patrón correcto
                transaction = Transaction([from_keypair], message, recent_blockhash)
                print("✅ Transacción creada y firmada con patrón oficial")
                
            except Exception as e:
                print(f"⚠️  Patrón oficial falló ({e}), usando método compatible...")
                
                # Método compatible para versiones anteriores
                transaction = Transaction.new_with_payer([transfer_instruction], from_keypair.pubkey())
                
                # Asignar blockhash de forma segura
                try:
                    setattr(transaction.message, 'recent_blockhash', recent_blockhash)
                except AttributeError:
                    # Si no se puede asignar al mensaje, intentar en la transacción
                    setattr(transaction, 'recent_blockhash', recent_blockhash)
                
                # Firmar transacción con blockhash
                try:
                    transaction.sign([from_keypair], recent_blockhash)
                except TypeError:
                    # Fallback sin blockhash en sign
                    transaction.sign([from_keypair])
                
                print("✅ Transacción creada y firmada con método compatible")

            # 5. Enviar transacción
            print("🔄 Enviando transacción a la red...")
            response = self.client.send_transaction(transaction)

            # 6. Procesar respuesta
            if response.value:
                signature = str(response.value)
                print("🎉 ¡Transferencia enviada exitosamente!")
                print(f"💰 Cantidad: {amount_sol} SOL")
                print(f"📍 Desde: {from_keypair.pubkey()}")
                print(f"📍 Hacia: {to_address}")
                print(f"🔗 Signature: {signature}")
                print(f"🌐 Explorer: https://explorer.solana.com/tx/{signature}?cluster={self.wallet_manager.network}")
                print("⏳ La transacción puede tardar unos segundos en confirmarse...")
                
                return signature
            else:
                print("❌ Error: La transacción no fue aceptada por la red")
                return None

        except Exception as e:
            print(f"❌ Error en transferencia SOL: {e}")
            print(f"🔍 Tipo de error: {type(e).__name__}")
            
            # Diagnóstico específico
            error_str = str(e).lower()
            if "recent_blockhash" in error_str or "blockhash" in error_str:
                print("💡 DIAGNÓSTICO: Problema con blockhash")
                print("   - Verifica que el blockhash sea reciente")
            elif "insufficient" in error_str:
                print("💡 DIAGNÓSTICO: Fondos insuficientes")
                print("   - Verifica balance SOL para transferencia + comisiones")
            elif "signature" in error_str:
                print("💡 DIAGNÓSTICO: Problema con firma")
                print("   - Verifica que el keypair sea correcto")
            
            return None

    def get_transfer_fee_estimate(self, amount_sol: float) -> Dict[str, Any]:
        """Estima comisiones de transferencia"""
        try:
            print("🔄 Calculando comisiones...")
            
            # Comisión típica de Solana
            fee_lamports = 5000
            fee_sol = fee_lamports / 1_000_000_000

            estimate = {
                'amount_sol': amount_sol,
                'fee_lamports': fee_lamports,
                'fee_sol': fee_sol,
                'total_cost_sol': amount_sol + fee_sol,
                'network': self.wallet_manager.network,
                'estimated_at': datetime.now().isoformat()
            }

            print("💸 Estimación de comisiones:")
            print(f"   💰 Cantidad a enviar: {estimate['amount_sol']} SOL")
            print(f"   💳 Comisión estimada: {estimate['fee_sol']:.9f} SOL")
            print(f"   📊 Costo total: {estimate['total_cost_sol']:.9f} SOL")

            return estimate

        except Exception as e:
            print(f"❌ Error estimando comisiones: {e}")
            return {
                'amount_sol': amount_sol,
                'fee_lamports': 5000,
                'fee_sol': 0.000005,
                'total_cost_sol': amount_sol + 0.000005,
                'network': self.wallet_manager.network
            }

    def request_airdrop(self, public_key: str, amount_sol: float = 1.0) -> Optional[str]:
        """Solicita SOL gratis en devnet/testnet (solo para pruebas)"""
        return self.airdrop_sol_devnet(public_key, amount_sol)
    
    def airdrop_sol_devnet(self, public_key: str, amount_sol: float = 1.0) -> bool:
        """Solicita SOL gratis en devnet/testnet (solo para pruebas)"""
        try:
            if self.wallet_manager.network not in ["devnet", "testnet"]:
                print("❌ Airdrop solo disponible en devnet/testnet")
                return False

            decoded = base58.b58decode(public_key)
            if len(decoded) != 32:
                print("❌ Dirección inválida para airdrop")
                return False

            pubkey = PublicKey.from_bytes(decoded)
            lamports = int(amount_sol * 1_000_000_000)

            response = self.client.request_airdrop(pubkey, lamports)

            if response.value:
                print("🎁 Airdrop solicitado exitosamente!")
                print(f"💰 Cantidad: {amount_sol} SOL")
                print(f"📍 Wallet: {public_key}")
                print(f"🔗 Signature: {response.value}")
                print("⏳ Espera unos segundos para que se confirme...")
                return True
            else:
                print("❌ Error solicitando airdrop")
                return False

        except Exception as e:
            print(f"❌ Error en airdrop: {e}")
            return False 