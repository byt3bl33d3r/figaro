"""add self_learning_max_runs and self_learning_run_count to scheduled_tasks

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-26 00:00:01.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('self_learning_max_runs', sa.Integer(), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('self_learning_run_count', sa.Integer(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('scheduled_tasks', 'self_learning_run_count')
    op.drop_column('scheduled_tasks', 'self_learning_max_runs')
