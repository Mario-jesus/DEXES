# -*- coding: utf-8 -*-
"""
Registro centralizado de exchanges con direcciones como identificadores principales.

El sistema usa direcciones de programas de Solana como identificadores únicos,
y mapea a nombres internos normalizados para representación.
"""
from typing import Optional, Dict

# Mapeo principal: dirección del programa -> nombre interno normalizado
# La dirección es la clave, el nombre interno es el valor
EXCHANGE_ADDRESS_TO_INTERNAL_NAME: Dict[str, str] = {
    # Pump.Fun | pump
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pump_fun",
    # PumpSwap | pump-amm
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "pump_swap",
    # Raydium LaunchLab | bonk
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": "raydium_launchlab",
}

# Mapeo inverso: nombre interno -> dirección (para búsqueda rápida)
INTERNAL_NAME_TO_ADDRESS: Dict[str, str] = {
    internal_name: address 
    for address, internal_name in EXCHANGE_ADDRESS_TO_INTERNAL_NAME.items()
}

# Mapeo de nombres de fuentes externas a nombres internos (fallback cuando no hay dirección)
SOURCE_NAME_TO_INTERNAL_NAME: Dict[str, str] = {
    # Moralis
    "Pump.Fun": "pump_fun",
    "PumpSwap": "pump_swap",
    "Raydium LaunchLab": "raydium_launchlab",
    # PumpPortal
    "pump": "pump_fun",
    "pump-amm": "pump_swap",
    "bonk": "raydium_launchlab",
}


def get_internal_name_by_address(exchange_address: Optional[str]) -> Optional[str]:
    """
    Obtiene el nombre interno normalizado por dirección del exchange.
    
    Args:
        exchange_address: Dirección del programa del exchange
    
    Returns:
        Nombre interno normalizado (ej: "pump_fun", "pump_swap") o None si no se conoce
    """
    if not exchange_address:
        return None
    return EXCHANGE_ADDRESS_TO_INTERNAL_NAME.get(exchange_address.strip())


def get_address_by_internal_name(internal_name: str) -> Optional[str]:
    """
    Obtiene la dirección del exchange por su nombre interno.
    
    Args:
        internal_name: Nombre interno normalizado (ej: "pump_fun", "pump_swap")
    
    Returns:
        Dirección del programa o None si no se conoce
    """
    return INTERNAL_NAME_TO_ADDRESS.get(internal_name)


def get_internal_name_by_source_name(source_name: Optional[str]) -> Optional[str]:
    """
    Obtiene el nombre interno a partir del nombre de la fuente externa.
    Se usa como fallback cuando no hay dirección disponible.
    
    Args:
        source_name: Nombre del exchange según la fuente (ej: "Pump.Fun", "pump")
    
    Returns:
        Nombre interno normalizado o None si no se conoce
    """
    if not source_name:
        return None
    return SOURCE_NAME_TO_INTERNAL_NAME.get(source_name.strip())


def normalize_exchange(
    exchange_address: Optional[str] = None,
    exchange_name: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """
    Normaliza un exchange a dirección y nombre interno.
    
    Prioriza la dirección si está disponible. Si no hay dirección conocida,
    intenta obtenerla desde el nombre de la fuente.
    Si no se puede normalizar, devuelve los valores originales de la fuente.
    
    Args:
        exchange_address: Dirección del programa del exchange (de la fuente de datos)
        exchange_name: Nombre del exchange según la fuente de datos
    
    Returns:
        Tupla (dirección, nombre_interno)
        - Si se encuentra la dirección en el registro: (dirección, nombre_interno_sistema)
        - Si la dirección no está en el registro pero existe: (dirección_original, exchange_name_original)
        - Si no hay dirección pero se puede mapear por nombre: (dirección_sistema, nombre_interno_sistema)
        - Si no se puede normalizar: (exchange_address_original, exchange_name_original)
    """
    # Prioridad 1: Si hay dirección, usarla directamente
    if exchange_address:
        address = exchange_address.strip()
        internal_name = get_internal_name_by_address(address)
        if internal_name:
            # Dirección conocida en el registro - usar nombre interno del sistema
            return address, internal_name
        else:
            # Dirección no conocida pero válida - devolver dirección y nombre original de la fuente
            return address, exchange_name.strip() if exchange_name else None

    # Prioridad 2: Si no hay dirección, intentar mapear desde el nombre de la fuente
    if exchange_name:
        internal_name = get_internal_name_by_source_name(exchange_name)
        if internal_name:
            # Obtener la dirección correspondiente si existe en el registro
            address = get_address_by_internal_name(internal_name)
            if address:
                # Tenemos dirección y nombre interno del sistema
                return address, internal_name
            else:
                # Solo tenemos nombre interno del sistema pero no dirección
                return None, internal_name
        else:
            # No se puede mapear - devolver valores originales de la fuente
            return None, exchange_name.strip()

    # No hay información disponible
    return None, None


def get_display_name(exchange_address: Optional[str], fallback_name: Optional[str] = None) -> str:
    """
    Obtiene un nombre para mostrar. Prioriza el nombre interno, usa fallback si no está disponible.
    
    Args:
        exchange_address: Dirección del exchange
        fallback_name: Nombre a usar si no se encuentra el nombre interno
    
    Returns:
        Nombre para mostrar
    """
    if exchange_address:
        internal_name = get_internal_name_by_address(exchange_address)
        if internal_name:
            return internal_name

    return fallback_name or exchange_address or "Unknown"
