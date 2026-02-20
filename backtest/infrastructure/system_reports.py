# -*- coding: utf-8 -*-
"""
Generate post-run analysis reports for copy-trading systems.

This module automates the same flow used in BACKTEST.ipynb:
- Load trader trades from Moralis JSON file (per trader wallet)
- Load system trades from PostgreSQL (per system wallet + trader wallet + run_id)
- Run backtests for trader and system
- Match closed trades and generate:
  - show_comparison output
  - show_losing_trades_comparison output
  - show_stats output (system)

Reports are stored under: <project_root>/reports/YYYY_mm_dd/
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, TypedDict, Tuple

import aiofiles
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from logging_system import setup_logging

from backtest.domain.services.backtest_validator import BacktestValidator
from backtest.infrastructure.adapters.presenters import (
    show_comparison,
    show_losing_trades_comparison,
    show_stats,
)
from backtest.infrastructure.container import Container

from copy_trading.persistence.orm.models import CopyTradingBot, Trader, Run

logger = logging.getLogger(__name__)


class SystemTraderPair(TypedDict):
    system_wallet_address: str
    trader_wallet: str


@dataclass(frozen=True)
class ReportPaths:
    comparison: Path
    losing_trades_comparison: Path
    system_stats: Path


_INVALID_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _project_root_from_here() -> Path:
    # This file: <root>/backtest/infrastructure/system_reports.py
    return Path(__file__).resolve().parents[2]


def _today_reports_folder_name() -> str:
    return datetime.now().strftime("%Y_%m_%d")


def _sanitize_filename_component(value: str, fallback: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS_RE.sub("_", (value or "").strip())
    cleaned = _MULTI_UNDERSCORE_RE.sub("_", cleaned).strip("_")
    return cleaned or fallback


def _resolve_path_from_root(path_str: str, project_root: Path) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (project_root / p)


def _validate_trader_files(
    systems: List[SystemTraderPair],
    trader_wallet_to_file: Dict[str, str],
    project_root: Path,
) -> Dict[str, Path]:
    requested_wallets = {p["trader_wallet"].strip() for p in systems if p.get("trader_wallet")}
    provided_wallets = {w.strip() for w in trader_wallet_to_file.keys()}

    missing = sorted(requested_wallets - provided_wallets)
    if missing:
        raise ValueError(
            "Missing trader trades file path for wallets: "
            + ", ".join(missing)
        )

    resolved: Dict[str, Path] = {}
    for wallet, file_path in trader_wallet_to_file.items():
        w = wallet.strip()
        if not w:
            continue
        resolved_path = _resolve_path_from_root(file_path, project_root)
        if w in requested_wallets and not resolved_path.exists():
            raise FileNotFoundError(f"Trades file not found for trader {w}: {resolved_path}")
        resolved[w] = resolved_path

    extra = sorted(provided_wallets - requested_wallets)
    if extra:
        logger.warning(
            "Trader trades file map includes extra wallets not requested: %s",
            ", ".join(extra),
        )

    return resolved


def _parse_started_at_date(started_at_date: Optional[str]) -> Optional[Tuple[datetime, datetime]]:
    if not started_at_date:
        return None
    try:
        day = datetime.strptime(started_at_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"Invalid started_at_date format (expected YYYY-mm-dd): {started_at_date}") from e
    return (day, day + timedelta(days=1))


def _find_latest_run_id(
    session,
    system_wallet_address: str,
    started_at_date: Optional[str] = None,
):
    stmt = select(Run).where(Run.copy_trading_bots_id == system_wallet_address)
    stmt = stmt.where(Run.started_at.isnot(None))

    day_range = _parse_started_at_date(started_at_date)
    if day_range is not None:
        day_start, day_end = day_range
        stmt = stmt.where(Run.started_at >= day_start, Run.started_at < day_end)

    stmt = stmt.order_by(Run.started_at.desc().nulls_last()).limit(1)
    run = session.execute(stmt).scalars().first()
    if not run:
        if started_at_date:
            raise ValueError(
                f"No run found for system_wallet_address={system_wallet_address} "
                f"on started_at date {started_at_date}"
            )
        raise ValueError(f"No run found for system_wallet_address={system_wallet_address}")
    return run.id


def _fetch_bot_and_trader_labels(session, system_wallet_address: str, trader_wallet: str) -> Tuple[str, str]:
    bot = session.get(CopyTradingBot, system_wallet_address)
    if bot is None:
        raise ValueError(f"CopyTradingBot not found for system_wallet_address={system_wallet_address}")

    trader = session.get(Trader, trader_wallet)
    nickname = trader.nickname if trader and trader.nickname else "Unknown"
    return (bot.name, nickname)


def _build_report_paths(
    reports_dir: Path,
    bot_name: str,
    trader_nickname: str,
    trader_wallet: str,
) -> ReportPaths:
    bot_suffix = (bot_name or "BOT")[-5:]
    wallet_prefix = (trader_wallet or "wallet")[:6]

    bot_part = _sanitize_filename_component(bot_suffix, "BOT")
    nick_part = _sanitize_filename_component(trader_nickname, "Unknown")
    wallet_part = _sanitize_filename_component(wallet_prefix, "wallet")

    def p(report_name: str) -> Path:
        return reports_dir / f"{bot_part}_{nick_part}_{wallet_part}_{report_name}.txt"

    return ReportPaths(
        comparison=p("comparison"),
        losing_trades_comparison=p("losing_trades_comparison"),
        system_stats=p("system_stats"),
    )


async def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)


def _clear_runner_cache(container: Container, source: str) -> None:
    """Clear the cache for the given repository source so the next backtest run is fresh."""
    cache = container.get_cache_service(source)
    clear = getattr(cache, "clear", None)
    if callable(clear):
        clear()
        logger.debug("Cache cleared for source=%s", source)


def _clear_all_runner_caches(container: Container) -> None:
    """Clear moralis and system caches so no stale backtest result is ever used when generating reports."""
    _clear_runner_cache(container, "moralis")
    _clear_runner_cache(container, "system")


async def generate_system_reports(
    systems: List[SystemTraderPair],
    trader_wallet_to_file: Dict[str, str],
    started_at_date: Optional[str] = None,
    include_liquidations: bool = True,
) -> None:
    """
    Generate and store reports for each (system_wallet_address, trader_wallet) pair.

    Args:
        systems: List of dicts with keys: system_wallet_address, trader_wallet
        trader_wallet_to_file: Mapping trader_wallet -> Moralis JSON trades file path
        started_at_date: Optional date filter for Run.started_at (format YYYY-mm-dd).
            If provided, selects the latest run within that date.
        include_liquidations: Whether to include liquidation positions in system repository load.
    """
    setup_logging(
        console_output=True,
        file_output=False,
        min_level_to_process="WARNING",
        enable_logfire=False,
    )

    if not systems:
        logger.warning("No systems provided; nothing to do.")
        return None

    project_root = _project_root_from_here()
    reports_dir = project_root / "reports" / _today_reports_folder_name()
    reports_dir.mkdir(parents=True, exist_ok=True)

    resolved_trader_files = _validate_trader_files(systems, trader_wallet_to_file, project_root)

    container = Container()

    # Use the same DB engine as the system repository (configured via BACKTEST_PG* env vars).
    system_repo = container.get_repository("system")
    engine = getattr(system_repo, "engine", None)
    if engine is None:
        raise RuntimeError("System repository does not expose a SQLAlchemy engine; cannot query runs via ORM.")

    SessionLocal = sessionmaker(bind=engine)

    comparator = container.get_backtest_comparator()

    # Never use backtest cache when generating reports: each run must use current repo data.
    _clear_all_runner_caches(container)

    trader_stats_cache: Dict[str, object] = {}

    for pair in systems:
        # Clear caches at the start of each pair so multiple traders never see stale results.
        _clear_all_runner_caches(container)

        system_wallet_address = pair.get("system_wallet_address", "").strip()
        trader_wallet = pair.get("trader_wallet", "").strip()

        if not system_wallet_address or not trader_wallet:
            raise ValueError(f"Invalid system/trader pair: {pair}")

        trader_file = resolved_trader_files[trader_wallet]

        with SessionLocal() as session:
            run_id = _find_latest_run_id(
                session=session,
                system_wallet_address=system_wallet_address,
                started_at_date=started_at_date,
            )
            bot_name, trader_nickname = _fetch_bot_and_trader_labels(
                session=session,
                system_wallet_address=system_wallet_address,
                trader_wallet=trader_wallet,
            )

        report_paths = _build_report_paths(
            reports_dir=reports_dir,
            bot_name=bot_name,
            trader_nickname=trader_nickname,
            trader_wallet=trader_wallet,
        )

        # Trader backtest (reuse in-memory result per trader_wallet only; never use runner cache)
        if trader_wallet not in trader_stats_cache:
            trader_repository = container.get_repository("moralis")
            trader_repository.load_from_file(file_path=str(trader_file))

            _clear_runner_cache(container, "moralis")
            trader_runner = container.get_backtest_runner("moralis")
            trader_validator = BacktestValidator()
            trader_stats_cache[trader_wallet] = trader_runner.run(validator=trader_validator)

        trader_stats = trader_stats_cache[trader_wallet]

        # System backtest (per system/run)
        system_repository = container.get_repository("system")
        system_repository.load_from_database(
            system_wallet_address=system_wallet_address,
            trader_wallet=trader_wallet,
            run_id=run_id,
            start_date=None,
            end_date=None,
            include_liquidations=include_liquidations,
            limit=None,
        )

        _clear_runner_cache(container, "system")
        system_runner = container.get_backtest_runner("system")
        system_validator = BacktestValidator()
        system_stats = system_runner.run(validator=system_validator)

        # Generate report texts
        comparison_text: str
        losing_text: str
        if trader_stats is not None and system_stats is not None:
            try:
                trader_matched, system_matched = comparator.compare_and_match_stats(
                    trader_stats=trader_stats,  # type: ignore[arg-type]
                    system_stats=system_stats,
                )
                comparison_text = show_comparison(
                    trader_stats=trader_matched,
                    system_stats=system_matched,
                    return_string=True,
                ) or ""
                losing_text = show_losing_trades_comparison(
                    trader_stats=trader_matched,
                    system_stats=system_matched,
                    return_string=True,
                ) or ""
            except Exception as e:
                comparison_text = f"Error generating comparison report: {e}"
                losing_text = f"Error generating losing trades comparison report: {e}"
        else:
            comparison_text = "Cannot compare: missing trader_stats or system_stats."
            losing_text = "Cannot compare losses: missing trader_stats or system_stats."

        system_stats_text = (
            show_stats(system_stats, return_string=True) if system_stats is not None else "No system stats found."
        ) or ""

        # Async write of the three reports
        await asyncio.gather(
            _write_text_file(report_paths.comparison, comparison_text),
            _write_text_file(report_paths.losing_trades_comparison, losing_text),
            _write_text_file(report_paths.system_stats, system_stats_text),
        )


def run_generate_system_reports(
    systems: List[SystemTraderPair],
    trader_wallet_to_file: Dict[str, str],
    started_at_date: Optional[str] = None,
    include_liquidations: bool = True,
) -> None:
    """Synchronous wrapper around generate_system_reports()."""
    asyncio.run(
        generate_system_reports(
            systems=systems,
            trader_wallet_to_file=trader_wallet_to_file,
            started_at_date=started_at_date,
            include_liquidations=include_liquidations,
        )
    )


if __name__ == "__main__":
    raise SystemExit(
        "This module is intended to be imported and executed programmatically.\n"
        "Use run_generate_system_reports(...) or asyncio.run(generate_system_reports(...))."
    )

