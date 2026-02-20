# -*- coding: utf-8 -*-
"""
Script para automatizar la descarga de swaps de múltiples wallets (traders).

Crea una carpeta con la fecha actual, genera un fichero por wallet con
nombre basado en los 6 primeros caracteres y el rango de fechas, y retorna
un diccionario wallet -> ruta del archivo guardado.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .swaps_client import MoralisSwapsClient

logger = logging.getLogger(__name__)

# Raíz del proyecto (DEXES) y carpeta por defecto para descargas
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_BASE_DIR = str(_PROJECT_ROOT / "data_moralis")


def _folder_name_from_today() -> str:
    """Nombre de carpeta con fecha actual: backtest_Y_m_d (ej. backtest_2026_02_19)."""
    return datetime.now().strftime("backtest_%Y_%m_%d")


def _file_name_for_wallet(wallet: str, from_date: str, to_date: str) -> str:
    """
    Nombre del fichero: 6 primeros caracteres de la wallet, from_date y to_date.
    Ejemplo: 2fg5QD_2026-02-12_2026-02-19.json
    """
    prefix = (wallet.strip() or "unknown")[:6]
    return f"{prefix}_{from_date}_{to_date}.json"


async def download_traders_swaps(
    wallets: List[str],
    from_date: str,
    base_dir: str = DEFAULT_BASE_DIR,
    **save_swaps_kwargs,
) -> Dict[str, str]:
    """
    Descarga los swaps de varias wallets y guarda cada una en un JSON.

    Parámetros:
        wallets: Lista de direcciones de wallet.
        from_date: Fecha de inicio en formato Y-m-d (ej. "2026-02-12").
        base_dir: Directorio base donde se creará la carpeta backtest_* (por defecto: data_moralis en la raíz del proyecto).
        **save_swaps_kwargs: Argumentos opcionales para save_swaps_to_file
            (token, limit_per_page, order, max_pages, single_page, transaction_types, etc.).

    Retorno:
        Diccionario con wallet como clave y ruta absoluta del archivo guardado como valor.
    """
    now_date = datetime.now().strftime("%Y-%m-%d")
    folder_name = _folder_name_from_today()
    output_dir = Path(base_dir) / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Misma configuración que en Moralis.ipynb; save_swaps_kwargs puede sobrescribir
    save_opts = {
        "token": None,
        "limit_per_page": 100,
        "from_date": from_date,
        "to_date": None,
        "order": "DESC",
        "max_pages": None,
        "single_page": False,
        "transaction_types": "buy,sell",
    }
    save_opts.update(save_swaps_kwargs)

    result: Dict[str, str] = {}

    async with MoralisSwapsClient() as client:
        for wallet in wallets:
            wallet = wallet.strip()
            if not wallet:
                continue
            file_name = _file_name_for_wallet(wallet, from_date, now_date)
            file_path = str(output_dir / file_name)
            try:
                path_saved = await client.save_swaps_to_file(
                    wallet=wallet,
                    file_path=file_path,
                    **save_opts,
                )
                result[wallet] = str(Path(path_saved).resolve())
            except Exception as e:
                logger.exception("Error descargando swaps para wallet %s: %s", wallet[:8], e)
                raise

    return result


def run_download_traders_swaps(
    wallets: List[str],
    from_date: str,
    base_dir: str = DEFAULT_BASE_DIR,
    **save_swaps_kwargs,
) -> Dict[str, str]:
    """
    Versión síncrona que ejecuta download_traders_swaps en el event loop.

    Mismos parámetros y retorno que download_traders_swaps.
    """
    return asyncio.run(
        download_traders_swaps(
            wallets=wallets,
            from_date=from_date,
            base_dir=base_dir,
            **save_swaps_kwargs,
        )
    )
