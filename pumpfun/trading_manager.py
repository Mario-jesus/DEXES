# -*- coding: utf-8 -*-
import requests
import json
import base58
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime

from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig

from solana_manager.wallet_manager import SolanaWalletManager


class PumpFunTrader:
    """
    Gestor de trading para Pump.fun usando PumpPortal API
    Integra con SolanaWalletManager para manejo de wallets
    """
    
    def __init__(self, wallet_manager: SolanaWalletManager):
        """
        Inicializa el trader de Pump.fun
        
        Args:
            wallet_manager: Instancia de SolanaWalletManager configurada
        """
        self.wallet_manager = wallet_manager
        self.pumpportal_api = "https://pumpportal.fun/api/trade-local"
        
        # Verificar que la wallet esté cargada
        if not self.wallet_manager.is_wallet_loaded():
            raise ValueError("❌ Wallet no cargada. Usa wallet_manager.load_wallet() primero")
        
        # Verificar que esté en mainnet
        if self.wallet_manager.network != "mainnet-beta":
            print("⚠️  ADVERTENCIA: Estás en", self.wallet_manager.network, "- para trading real usa mainnet-beta")
        
        print("🎯 PumpFun Trader inicializado")
        print(f"📍 Wallet: {self.wallet_manager.get_address()}")
        print(f"🌐 Red: {self.wallet_manager.network}")
    
    def create_trade_transaction(self, 
                                token_mint: str,
                                action: str,
                                amount: float,
                                denominated_in_sol: bool = True,
                                slippage: float = 10.0,
                                priority_fee: float = 0.00001,
                                pool: str = "pump") -> Optional[bytes]:
        """
        Crea una transacción de trading usando PumpPortal API
        
        Args:
            token_mint: Dirección del contrato del token
            action: "buy" o "sell"
            amount: Cantidad a tradear
            denominated_in_sol: True si amount es en SOL, False si es en tokens
            slippage: Porcentaje de slippage permitido
            priority_fee: Fee de prioridad
            pool: "pump", "raydium", o "auto"
            
        Returns:
            Transacción serializada o None si hay error
        """
        try:
            # Preparar parámetros
            params = {
                "publicKey": self.wallet_manager.get_address(),
                "action": action,
                "mint": token_mint,
                "amount": amount,
                "denominatedInSol": str(denominated_in_sol).lower(),
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": pool
            }
            
            print(f"🔄 Creando transacción {action.upper()} para {token_mint}")
            print(f"💰 Cantidad: {amount} {'SOL' if denominated_in_sol else 'tokens'}")
            print(f"📊 Slippage: {slippage}% | Fee: {priority_fee} SOL")
            
            # Hacer request a PumpPortal
            response = requests.post(
                self.pumpportal_api,
                json=params,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                print("✅ Transacción creada exitosamente")
                return response.content
            else:
                print(f"❌ Error en PumpPortal: {response.status_code}")
                print(f"📄 Respuesta: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Error creando transacción: {e}")
            return None
    
    def execute_trade(self,
                        token_mint: str,
                        action: str,
                        amount: float,
                        denominated_in_sol: bool = True,
                        slippage: float = 10.0,
                        priority_fee: float = 0.00001,
                        pool: str = "pump") -> Optional[str]:
        """
        Ejecuta un trade completo: crear, firmar y enviar transacción
        
        Returns:
            Signature de la transacción o None si hay error
        """
        try:
            # Crear transacción
            serialized_tx = self.create_trade_transaction(
                token_mint, action, amount, denominated_in_sol, 
                slippage, priority_fee, pool
            )
            
            if not serialized_tx:
                return None
            
            # Deserializar transacción
            tx = VersionedTransaction.from_bytes(serialized_tx)
            
            # Firmar con la wallet
            signed_tx = VersionedTransaction(tx.message, [self.wallet_manager.keypair])
            
            # Enviar transacción usando el método correcto de PumpPortal
            print("📡 Enviando transacción...")
            
            # Configurar commitment y config según documentación oficial
            commitment = CommitmentLevel.Confirmed
            config = RpcSendTransactionConfig(preflight_commitment=commitment)
            tx_payload = SendVersionedTransaction(signed_tx, config)
            
            # Usar el RPC endpoint correcto
            rpc_url = self.wallet_manager.rpc_urls[self.wallet_manager.network]
            
            # Enviar usando requests con el método JSON-RPC correcto
            response = requests.post(
                url=rpc_url,
                headers={"Content-Type": "application/json"},
                data=tx_payload.to_json(),
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'result' in result and result['result']:
                    signature = result['result']
                    print(f"✅ Trade ejecutado exitosamente!")
                    print(f"🔗 Signature: {signature}")
                    print(f"🌐 Explorer: https://solscan.io/tx/{signature}")
                    return signature
                else:
                    print(f"❌ Error en respuesta RPC: {result}")
                    return None
            else:
                print(f"❌ Error HTTP: {response.status_code}")
                print(f"📄 Respuesta: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Error ejecutando trade: {e}")
            return None
    
    def buy_token(self,
                    token_mint: str,
                    sol_amount: float,
                    slippage: float = 10.0,
                    priority_fee: float = 0.00001) -> Optional[str]:
        """
        Compra tokens con SOL
        
        Args:
            token_mint: Dirección del contrato del token
            sol_amount: Cantidad de SOL a gastar
            slippage: Porcentaje de slippage
            priority_fee: Fee de prioridad
            
        Returns:
            Signature de la transacción
        """
        print(f"🛒 COMPRANDO {sol_amount} SOL de token {token_mint}")
        return self.execute_trade(
            token_mint=token_mint,
            action="buy",
            amount=sol_amount,
            denominated_in_sol=True,
            slippage=slippage,
            priority_fee=priority_fee
        )
    
    def sell_token(self,
                    token_mint: str,
                    token_amount: float,
                    slippage: float = 10.0,
                    priority_fee: float = 0.00001) -> Optional[str]:
        """
        Vende tokens por SOL
        
        Args:
            token_mint: Dirección del contrato del token
            token_amount: Cantidad de tokens a vender (o porcentaje como "100%")
            slippage: Porcentaje de slippage
            priority_fee: Fee de prioridad
            
        Returns:
            Signature de la transacción
        """
        print(f"💸 VENDIENDO {token_amount} tokens de {token_mint}")
        return self.execute_trade(
            token_mint=token_mint,
            action="sell",
            amount=token_amount,
            denominated_in_sol=False,
            slippage=slippage,
            priority_fee=priority_fee
        )
    
    def sell_all_tokens(self,
                        token_mint: str,
                        slippage: float = 10.0,
                        priority_fee: float = 0.00001) -> Optional[str]:
        """
        Vende todos los tokens (100%)
        
        Args:
            token_mint: Dirección del contrato del token
            slippage: Porcentaje de slippage
            priority_fee: Fee de prioridad
            
        Returns:
            Signature de la transacción
        """
        print(f"💸 VENDIENDO TODOS los tokens de {token_mint}")
        return self.execute_trade(
            token_mint=token_mint,
            action="sell",
            amount="100%",
            denominated_in_sol=False,
            slippage=slippage,
            priority_fee=priority_fee
        )
    
    def get_wallet_info(self) -> Dict[str, Any]:
        """
        Obtiene información de la wallet actual
        
        Returns:
            Diccionario con información de la wallet
        """
        return {
            "address": self.wallet_manager.get_address(),
            "network": self.wallet_manager.network,
            "rpc_url": self.wallet_manager.rpc_urls[self.wallet_manager.network],
            "is_loaded": self.wallet_manager.is_wallet_loaded()
        }
    
    def estimate_trade_cost(self,
                            sol_amount: float,
                            priority_fee: float = 0.00001) -> Dict[str, float]:
        """
        Estima el costo total de un trade
        
        Args:
            sol_amount: Cantidad de SOL para el trade
            priority_fee: Fee de prioridad
            
        Returns:
            Diccionario con estimación de costos
        """
        # Fees estimados
        network_fee = 0.000005  # Fee típico de red Solana
        pumpportal_fee = 0.0  # Local API es gratuita
        
        total_cost = sol_amount + priority_fee + network_fee
        
        return {
            "trade_amount": sol_amount,
            "priority_fee": priority_fee,
            "network_fee": network_fee,
            "pumpportal_fee": pumpportal_fee,
            "total_cost": total_cost,
            "effective_trade": sol_amount  # En Local API no hay fee de PumpPortal
        } 