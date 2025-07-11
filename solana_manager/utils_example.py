#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejemplo de uso de SolanaUtils independiente

Este ejemplo demuestra cómo usar SolanaUtils de forma completamente independiente,
sin necesidad de SolanaWalletManager. La clase se conecta directamente a la red
Solana usando AsyncClient.

Características demostradas:
- Conexión directa a diferentes redes de Solana
- Validación de direcciones
- Conversiones de unidades
- Obtención de precios
- Operaciones en lote
- Manejo de errores

Autor: DEXES Team
"""

import asyncio
from utils import SolanaUtils


async def ejemplo_basico():
    """Ejemplo básico de uso de SolanaUtils."""
    print("🚀 Ejemplo básico de SolanaUtils")
    print("=" * 50)
    
    # Conectar a mainnet-beta (por defecto)
    async with SolanaUtils() as utils:
        print("\n1. Validación de direcciones:")
        direcciones = [
            "11111111111111111111111111111112",  # Válida (System Program)
            "invalid_address_123",               # Inválida
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"  # Válida
        ]
        
        for addr in direcciones:
            is_valid = await utils.validate_address(addr)
            print(f"   {addr}: {'✅ Válida' if is_valid else '❌ Inválida'}")
        
        print("\n2. Conversiones de unidades:")
        lamports = 1500000000  # 1.5 SOL
        sol = await utils.convert_lamports_to_sol(lamports)
        lamports_back = await utils.convert_sol_to_lamports(sol)
        
        print(f"   {lamports:,} lamports = {sol} SOL")
        print(f"   {sol} SOL = {lamports_back:,} lamports")
        
        print("\n3. Formateo de balance:")
        formatted = await utils.format_balance(lamports)
        print(f"   Balance formateado: {formatted}")
        
        print("\n4. Precio de SOL:")
        price = await utils.get_solana_price_usd()
        if price > 0:
            value = await utils.calculate_sol_value_usd(sol)
            print(f"   {sol} SOL = ${value:.2f} USD")


async def ejemplo_redes():
    """Ejemplo de conexión a diferentes redes."""
    print("\n🌐 Ejemplo de conexión a diferentes redes")
    print("=" * 50)
    
    redes = ["devnet", "mainnet-beta"]
    
    for red in redes:
        print(f"\nConectando a {red}:")
        try:
            async with SolanaUtils(network=red) as utils:
                info = await utils.get_network_info()
                if info:
                    print(f"   ✅ Conectado a {info['network']}")
                    print(f"   📊 Slot actual: {info['current_slot']:,}")
                else:
                    print(f"   ❌ No se pudo obtener información de {red}")
        except Exception as e:
            print(f"   ❌ Error conectando a {red}: {e}")


async def ejemplo_rpc_personalizado():
    """Ejemplo de uso con RPC personalizado."""
    print("\n🔧 Ejemplo con RPC personalizado")
    print("=" * 50)
    
    # Usar un RPC personalizado (ejemplo con QuickNode)
    rpc_personalizado = "https://your-custom-rpc-endpoint.com"
    
    try:
        async with SolanaUtils(network="mainnet-beta", rpc_url=rpc_personalizado) as utils:
            print("   🔗 Conectado con RPC personalizado")
            info = await utils.get_network_info()
            if info:
                print(f"   📊 Slot actual: {info['current_slot']:,}")
    except Exception as e:
        print(f"   ❌ Error con RPC personalizado: {e}")
        print("   💡 Nota: Este ejemplo requiere un endpoint RPC válido")


async def ejemplo_operaciones_lote():
    """Ejemplo de operaciones en lote."""
    print("\n📦 Ejemplo de operaciones en lote")
    print("=" * 50)
    
    async with SolanaUtils() as utils:
        # Conversión en lote de lamports
        lamports_list = [1000000000, 500000000, 10000000, 2500000000]
        print("   Conversión en lote de lamports:")
        sol_list = await utils.batch_convert_lamports(lamports_list)
        
        for i, (lamports, sol) in enumerate(zip(lamports_list, sol_list)):
            print(f"   {i+1}. {lamports:,} lamports = {sol} SOL")
        
        # Validación en lote de direcciones
        direcciones = [
            "11111111111111111111111111111112",
            "invalid_address",
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
            "another_invalid_address"
        ]
        
        print("\n   Validación en lote de direcciones:")
        info_direcciones = await utils.get_multiple_addresses_info(direcciones)
        
        for addr, info in info_direcciones.items():
            status = "✅ Válida" if info['valid'] else "❌ Inválida"
            print(f"   {addr}: {status}")


async def ejemplo_estado_red():
    """Ejemplo de obtención del estado de la red."""
    print("\n📡 Ejemplo de estado de la red")
    print("=" * 50)
    
    async with SolanaUtils() as utils:
        status = await utils.get_network_status()
        
        if status.get('connected'):
            print("   🌐 Estado de la red:")
            print(f"      Red: {status['network']}")
            print(f"      Slot actual: {status['current_slot']:,}")
            print(f"      Timestamp: {status['timestamp']}")
        else:
            print(f"   ❌ Estado: {status.get('status', 'desconocido')}")
            if 'error' in status:
                print(f"      Error: {status['error']}")


async def ejemplo_manejo_errores():
    """Ejemplo de manejo de errores."""
    print("\n⚠️ Ejemplo de manejo de errores")
    print("=" * 50)
    
    # Intentar conectar a una red inexistente
    try:
        async with SolanaUtils(network="red_inexistente") as utils:
            print("   Esto no debería ejecutarse")
    except ValueError as e:
        print(f"   ✅ Error capturado correctamente: {e}")
    
    # Usar SolanaUtils sin conexión a red
    utils = SolanaUtils()
    
    # Estas operaciones no requieren conexión
    is_valid = await utils.validate_address("11111111111111111111111111111112")
    print(f"   ✅ Validación sin conexión: {is_valid}")
    
    sol = await utils.convert_lamports_to_sol(1000000000)
    print(f"   ✅ Conversión sin conexión: {sol} SOL")
    
    # Esta operación requiere conexión
    info = await utils.get_network_info()
    if not info:
        print("   ✅ Error manejado correctamente: No hay conexión a la red")


async def main():
    """Función principal que ejecuta todos los ejemplos."""
    print("🎯 SolanaUtils - Ejemplos de uso independiente")
    print("=" * 60)
    
    try:
        await ejemplo_basico()
        await ejemplo_redes()
        await ejemplo_rpc_personalizado()
        await ejemplo_operaciones_lote()
        await ejemplo_estado_red()
        await ejemplo_manejo_errores()
        
        print("\n✅ Todos los ejemplos completados exitosamente!")
        
    except Exception as e:
        print(f"\n❌ Error en los ejemplos: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Ejecutar el ejemplo
    asyncio.run(main()) 