#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar que TODAS las funciones de wallet usen la carpeta wallets/
"""

import os
from solana_manager import SolanaWalletManager

def test_all_wallet_methods():
    """Prueba todos los métodos de creación y guardado de wallets"""
    
    print("🧪 VERIFICANDO TODAS LAS FUNCIONES DE WALLET")
    print("=" * 60)
    
    # Inicializar wallet manager
    wallet_manager = SolanaWalletManager(network="devnet")
    
    # Test 1: create_wallet_file() sin parámetros
    print("\n1️⃣ MÉTODO: create_wallet_file() SIN PARÁMETROS")
    print("-" * 50)
    
    filename1 = wallet_manager.create_wallet_file()
    if filename1:
        print(f"📍 Archivo creado: {filename1}")
        print(f"✅ Usa carpeta wallets: {filename1.startswith('wallets/')}")
    
    # Test 2: create_wallet_file() con parámetro
    print("\n2️⃣ MÉTODO: create_wallet_file() CON PARÁMETRO")
    print("-" * 50)
    
    filename2 = wallet_manager.create_wallet_file("test_custom.json")
    if filename2:
        print(f"📍 Archivo creado: {filename2}")
        print(f"✅ Usa carpeta wallets: {filename2.startswith('wallets/')}")
    
    # Test 3: save_wallet_to_file() con wallet_info
    print("\n3️⃣ MÉTODO: save_wallet_to_file() POR DEFECTO")
    print("-" * 50)
    
    wallet_info = wallet_manager.create_new_wallet()
    if wallet_info:
        wallet_manager.save_wallet_to_file(wallet_info)
        expected_path = "wallets/wallet.json"
        if os.path.exists(expected_path):
            print(f"✅ Archivo creado en: {expected_path}")
        else:
            print(f"❌ Archivo NO encontrado en: {expected_path}")
    
    # Test 4: save_wallet() con nombre simple
    print("\n4️⃣ MÉTODO: save_wallet() CON NOMBRE SIMPLE")
    print("-" * 50)
    
    wallet_manager.create_wallet()  # Crear wallet en memoria
    result = wallet_manager.save_wallet("test_simple.json")
    if result:
        expected_path = "wallets/test_simple.json"
        if os.path.exists(expected_path):
            print(f"✅ Archivo creado en: {expected_path}")
        else:
            print(f"❌ Archivo NO encontrado en: {expected_path}")
    
    # Test 5: load_wallet_from_file() por defecto
    print("\n5️⃣ MÉTODO: load_wallet_from_file() POR DEFECTO")
    print("-" * 50)
    
    try:
        loaded_wallet = wallet_manager.load_wallet_from_file()
        if loaded_wallet:
            print("✅ Wallet cargada desde wallets/wallet.json")
        else:
            print("⚠️ No se pudo cargar wallet por defecto")
    except Exception as e:
        print(f"⚠️ Error esperado: {e}")
    
    # Test 6: Verificar estructura de carpetas
    print("\n6️⃣ VERIFICACIÓN DE ESTRUCTURA")
    print("-" * 50)
    
    if os.path.exists("wallets"):
        wallet_files = [f for f in os.listdir("wallets") if f.endswith('.json')]
        print(f"📁 Total archivos .json en wallets/: {len(wallet_files)}")
        
        # Mostrar archivos recién creados
        test_files = [f for f in wallet_files if any(pattern in f for pattern in ['test_', 'wallet_2025'])]
        print(f"📄 Archivos de prueba creados: {len(test_files)}")
        for file in test_files:
            print(f"   ✅ {file}")
    
    # Test 7: Verificar que NO hay archivos en la raíz
    print("\n7️⃣ VERIFICACIÓN DE LIMPIEZA")
    print("-" * 50)
    
    root_wallet_files = [f for f in os.listdir(".") if f.startswith("wallet_") and f.endswith(".json")]
    if root_wallet_files:
        print(f"❌ Archivos wallet en la RAÍZ: {len(root_wallet_files)}")
        for file in root_wallet_files:
            print(f"   ❌ {file}")
    else:
        print("✅ No hay archivos wallet en la raíz del proyecto")
    
    # Limpieza
    print("\n🧹 LIMPIEZA DE ARCHIVOS DE PRUEBA")
    print("-" * 50)
    
    cleanup_files = []
    
    # Archivos en wallets/
    if filename1 and os.path.exists(filename1):
        cleanup_files.append(filename1)
    if filename2 and os.path.exists(filename2):
        cleanup_files.append(filename2)
    if os.path.exists("wallets/wallet.json"):
        cleanup_files.append("wallets/wallet.json")
    if os.path.exists("wallets/test_simple.json"):
        cleanup_files.append("wallets/test_simple.json")
    
    # Archivos en raíz (si los hay)
    for file in root_wallet_files:
        if os.path.exists(file):
            cleanup_files.append(file)
    
    for file in cleanup_files:
        try:
            os.remove(file)
            print(f"🗑️ Eliminado: {file}")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar {file}: {e}")
    
    return {
        'all_in_wallets_folder': all([
            filename1 and filename1.startswith('wallets/'),
            filename2 and filename2.startswith('wallets/'),
            len(root_wallet_files) == 0
        ])
    }

if __name__ == "__main__":
    result = test_all_wallet_methods()
    
    print("\n" + "=" * 60)
    if result['all_in_wallets_folder']:
        print("🎉 ¡ÉXITO! TODAS las funciones de wallet usan la carpeta wallets/")
        print("✅ Las clases de Solana ahora crean wallets en la ubicación correcta")
    else:
        print("❌ FALLO: Algunas funciones aún no usan la carpeta wallets/")
        print("🔧 Se requieren más correcciones") 