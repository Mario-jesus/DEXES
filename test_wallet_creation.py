#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar que las wallets se creen en la carpeta wallets/
"""

import os
from solana_manager import SolanaWalletManager

def test_wallet_creation_location():
    """Prueba la creación de wallets y verifica la ubicación"""
    
    print("🧪 VERIFICANDO CREACIÓN DE WALLETS")
    print("=" * 50)
    
    # Inicializar wallet manager
    wallet_manager = SolanaWalletManager(network="devnet")
    
    # Test 1: Crear wallet sin especificar carpeta (comportamiento actual)
    print("\n1️⃣ CREACIÓN SIN ESPECIFICAR CARPETA:")
    print("-" * 40)
    
    filename1 = wallet_manager.create_wallet_file()
    if filename1:
        print(f"📍 Archivo creado: {filename1}")
        print(f"📂 Ubicación actual: {os.path.abspath(filename1)}")
        
        # Verificar si está en la raíz del proyecto
        if "/" not in filename1 and "\\\\" not in filename1:
            print("⚠️  Wallet creada en la RAÍZ del proyecto")
        else:
            print("✅ Wallet creada en subdirectorio")
    
    # Test 2: Crear wallet especificando carpeta wallets/
    print("\n2️⃣ CREACIÓN ESPECIFICANDO CARPETA wallets/:")
    print("-" * 40)
    
    filename2 = wallet_manager.create_wallet_file("wallets/test_wallet.json")
    if filename2:
        print(f"📍 Archivo creado: {filename2}")
        print(f"📂 Ubicación absoluta: {os.path.abspath(filename2)}")
        
        # Verificar si está en wallets/
        if filename2.startswith("wallets/"):
            print("✅ Wallet creada CORRECTAMENTE en carpeta wallets/")
        else:
            print("❌ Wallet NO está en carpeta wallets/")
    
    # Test 3: Verificar archivos creados
    print("\n3️⃣ VERIFICACIÓN DE ARCHIVOS:")
    print("-" * 40)
    
    files_created = []
    if filename1 and os.path.exists(filename1):
        files_created.append(filename1)
    if filename2 and os.path.exists(filename2):
        files_created.append(filename2)
    
    for file in files_created:
        size = os.path.getsize(file)
        print(f"📄 {file}: {size} bytes")
    
    # Test 4: Verificar contenido de carpeta wallets/
    print("\n4️⃣ CONTENIDO DE CARPETA wallets/:")
    print("-" * 40)
    
    if os.path.exists("wallets"):
        wallet_files = [f for f in os.listdir("wallets") if f.endswith('.json')]
        print(f"📁 Archivos .json en wallets/: {len(wallet_files)}")
        for file in wallet_files:
            print(f"   📄 {file}")
    else:
        print("❌ Carpeta wallets/ no existe")
    
    # Test 5: Problema identificado y solución
    print("\n🔍 ANÁLISIS DEL PROBLEMA:")
    print("-" * 40)
    
    if filename1 and not filename1.startswith("wallets/"):
        print("❌ PROBLEMA ENCONTRADO:")
        print("   Las wallets se crean en la RAÍZ del proyecto")
        print("   en lugar de la carpeta wallets/")
        print()
        print("💡 SOLUCIÓN REQUERIDA:")
        print("   Modificar create_wallet_file() para usar")
        print("   'wallets/' como directorio por defecto")
    else:
        print("✅ No se detectaron problemas")
    
    # Limpiar archivos de prueba
    print("\n🧹 LIMPIEZA:")
    print("-" * 40)
    
    cleanup_files = []
    if filename1 and filename1.startswith("wallet_"):
        cleanup_files.append(filename1)
    if filename2 and filename2 == "wallets/test_wallet.json":
        cleanup_files.append(filename2)
    
    for file in cleanup_files:
        try:
            if os.path.exists(file):
                os.remove(file)
                print(f"🗑️ Eliminado: {file}")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar {file}: {e}")
    
    return {
        'filename1': filename1,
        'filename2': filename2,
        'problem_detected': filename1 and not filename1.startswith("wallets/")
    }

if __name__ == "__main__":
    result = test_wallet_creation_location()
    
    if result['problem_detected']:
        print("\n🚨 ACCIÓN REQUERIDA:")
        print("Las clases de Solana NO están creando wallets en la carpeta wallets/")
        print("Se requiere modificar el código para corregir esto.")
    else:
        print("\n✅ TODO CORRECTO:")
        print("Las wallets se están creando en la ubicación correcta.") 