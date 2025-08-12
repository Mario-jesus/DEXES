# -*- coding: utf-8 -*-
"""
Utilidades de serialización para modelos de posiciones.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any


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
