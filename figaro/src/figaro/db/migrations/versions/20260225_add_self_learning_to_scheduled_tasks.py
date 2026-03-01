"""add self_learning to scheduled_tasks

Revision ID: a1b2c3d4e5f6
Revises: 30b18e453168
Create Date: 2026-02-25 22:53:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '30b18e453168'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('self_learning', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('scheduled_tasks', 'self_learning')
