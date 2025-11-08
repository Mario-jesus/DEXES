"""Initial schema with PNL tables

Revision ID: 654f26037b5d
Revises: 
Create Date: 2025-11-06 21:52:45.348653

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '654f26037b5d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Crear tablas base
    op.create_table('mints',
        sa.Column('mint_address', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=True),
        sa.Column('symbol', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('mint_address')
    )

    op.create_table('traders',
        sa.Column('wallet_address', sa.String(length=50), nullable=False),
        sa.Column('nickname', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('wallet_address')
    )

    op.create_table('copy_trading_bots',
        sa.Column('system_wallet_address', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('system_wallet_address')
    )

    op.create_table('runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('is_dry_run', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('initial_capital_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('final_capital_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('copy_trading_bots_id', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['copy_trading_bots_id'], ['copy_trading_bots.system_wallet_address'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_runs_copy_trading_bots_id'), 'runs', ['copy_trading_bots_id'], unique=False)

    op.create_table('run_mints',
        sa.Column('runs_id', sa.UUID(), nullable=False),
        sa.Column('mints_id', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['mints_id'], ['mints.mint_address'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['runs_id'], ['runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('runs_id', 'mints_id')
    )

    op.create_table('run_traders',
        sa.Column('runs_id', sa.UUID(), nullable=False),
        sa.Column('traders_id', sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(['runs_id'], ['runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['traders_id'], ['traders.wallet_address'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('runs_id', 'traders_id')
    )

    op.create_table('positions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('fee_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('total_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('signature', sa.String(length=100), nullable=True),
        sa.Column('side', sa.Enum('BUY', 'SELL', name='side'), nullable=False),
        sa.Column('is_analyzed', sa.Boolean(), nullable=False),
        sa.Column('is_liquidation', sa.Boolean(), nullable=False),
        sa.Column('message_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('runs_id', sa.UUID(), nullable=False),
        sa.Column('mints_id', sa.String(length=50), nullable=False),
        sa.Column('traders_id', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['mints_id'], ['mints.mint_address'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['runs_id'], ['runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['traders_id'], ['traders.wallet_address'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('signature')
    )
    op.create_index(op.f('ix_positions_mints_id'), 'positions', ['mints_id'], unique=False)
    op.create_index(op.f('ix_positions_runs_id'), 'positions', ['runs_id'], unique=False)
    op.create_index(op.f('ix_positions_traders_id'), 'positions', ['traders_id'], unique=False)

    op.create_table('open_positions',
        sa.Column('positions_id', sa.UUID(), nullable=False),
        sa.Column('sol_amount_sent', sa.DECIMAL(precision=18, scale=9), nullable=False),
        sa.Column('sol_amount_executed', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('token_amount_received', sa.DECIMAL(precision=18, scale=6), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'OPEN', 'PARTIALLY_CLOSED', 'CLOSED', 'FAILED', name='openpositionstatus'), nullable=False),
        sa.ForeignKeyConstraint(['positions_id'], ['positions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('positions_id')
    )

    op.create_table('trader_trade_data',
        sa.Column('positions_id', sa.UUID(), nullable=False),
        sa.Column('sol_amount', sa.DECIMAL(precision=18, scale=9), nullable=False),
        sa.Column('token_amount', sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column('new_token_balance', sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column('signature', sa.String(length=100), nullable=False),
        sa.Column('pool', sa.String(length=15), nullable=False),
        sa.Column('bonding_curve_key', sa.String(length=50), nullable=False),
        sa.Column('v_sol_in_bonding_curve', sa.DECIMAL(precision=18, scale=9), nullable=False),
        sa.Column('v_tokens_in_bonding_curve', sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column('market_cap_sol', sa.DECIMAL(precision=18, scale=9), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['positions_id'], ['positions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('positions_id')
    )

    op.create_table('close_orders',
        sa.Column('positions_id', sa.UUID(), nullable=False),
        sa.Column('open_positions_id', sa.UUID(), nullable=True),
        sa.Column('token_amount_sent', sa.DECIMAL(precision=18, scale=6), nullable=True),
        sa.Column('sol_amount_received', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'PARTIAL', 'SUCCESS', 'FAILED', name='closeorderstatus'), nullable=False),
        sa.ForeignKeyConstraint(['open_positions_id'], ['open_positions.positions_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['positions_id'], ['positions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('positions_id')
    )

    op.create_table('partial_close_orders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('close_orders_id', sa.UUID(), nullable=False),
        sa.Column('open_positions_id', sa.UUID(), nullable=True),
        sa.Column('token_amount_sent', sa.DECIMAL(precision=18, scale=6), nullable=True),
        sa.Column('sol_amount_received', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('total_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('message_error', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'SUCCESS', 'FAILED', name='partialcloseorderstatus'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['close_orders_id'], ['close_orders.positions_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['open_positions_id'], ['open_positions.positions_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Tablas de PNL
    op.create_table('pnl_realized_mint',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('runs_id', sa.UUID(), nullable=False),
        sa.Column('mints_id', sa.String(length=50), nullable=False),
        sa.Column('pnl_without_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_without_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('total_volume_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.ForeignKeyConstraint(['runs_id', 'mints_id'], ['run_mints.runs_id', 'run_mints.mints_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('runs_id', 'mints_id', name='uq_pnl_realized_mint_runs_id_mints_id')
    )

    op.create_table('pnl_realized_trader',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('runs_id', sa.UUID(), nullable=False),
        sa.Column('traders_id', sa.String(length=50), nullable=False),
        sa.Column('pnl_without_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_without_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('total_volume_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.ForeignKeyConstraint(['runs_id', 'traders_id'], ['run_traders.runs_id', 'run_traders.traders_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('runs_id', 'traders_id', name='uq_pnl_realized_trader_runs_id_traders_id')
    )

    op.create_table('pnl_realized_position',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('open_positions_id', sa.UUID(), nullable=False),
        sa.Column('pnl_without_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_without_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.Column('pnl_with_cost_pct_sol', sa.DECIMAL(precision=18, scale=9), nullable=True),
        sa.ForeignKeyConstraint(['open_positions_id'], ['open_positions.positions_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('open_positions_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Eliminar tablas de PNL
    op.drop_table('pnl_realized_position')
    op.drop_table('pnl_realized_trader')
    op.drop_table('pnl_realized_mint')

    # Eliminar tablas dependientes
    op.drop_table('partial_close_orders')
    op.drop_table('close_orders')
    op.drop_table('trader_trade_data')
    op.drop_table('open_positions')

    # Eliminar tabla positions e índices
    op.drop_index(op.f('ix_positions_traders_id'), table_name='positions')
    op.drop_index(op.f('ix_positions_runs_id'), table_name='positions')
    op.drop_index(op.f('ix_positions_mints_id'), table_name='positions')
    op.drop_table('positions')

    # Eliminar tablas de relación
    op.drop_table('run_traders')
    op.drop_table('run_mints')

    # Eliminar tabla runs e índice
    op.drop_index(op.f('ix_runs_copy_trading_bots_id'), table_name='runs')
    op.drop_table('runs')

    # Eliminar tablas base
    op.drop_table('copy_trading_bots')
    op.drop_table('traders')
    op.drop_table('mints')

    # Eliminar tipos ENUM
    op.execute("DROP TYPE IF EXISTS partialcloseorderstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS closeorderstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS openpositionstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS side CASCADE")
