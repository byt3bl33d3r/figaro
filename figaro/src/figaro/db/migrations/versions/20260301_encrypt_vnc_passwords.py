"""encrypt vnc passwords with pgcrypto and add settings table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-01 00:00:01.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Create figaro_settings table
    op.create_table(
        'figaro_settings',
        sa.Column('id', sa.Integer(), primary_key=True, server_default='1'),
        sa.Column('vnc_password', sa.LargeBinary(), nullable=True),
        sa.CheckConstraint('id = 1', name='figaro_settings_single_row'),
    )

    # Seed default VNC password (encrypted)
    op.execute(
        sa.text(
            "INSERT INTO figaro_settings (id, vnc_password) "
            "VALUES (1, pgp_sym_encrypt('vscode', current_setting('app.encryption_key', true)))"
        )
    )

    # Convert desktop_workers.vnc_password from String to encrypted bytea
    # 1. Add temporary bytea column
    op.add_column('desktop_workers', sa.Column('vnc_password_enc', sa.LargeBinary(), nullable=True))

    # 2. Migrate existing plaintext passwords to encrypted
    op.execute(
        sa.text(
            "UPDATE desktop_workers SET vnc_password_enc = "
            "pgp_sym_encrypt(vnc_password, current_setting('app.encryption_key', true)) "
            "WHERE vnc_password IS NOT NULL"
        )
    )

    # 3. Drop old column and rename new one
    op.drop_column('desktop_workers', 'vnc_password')
    op.alter_column('desktop_workers', 'vnc_password_enc', new_column_name='vnc_password')


def downgrade() -> None:
    # Convert back to plaintext
    op.add_column('desktop_workers', sa.Column('vnc_password_text', sa.String(255), nullable=True))
    op.execute(
        sa.text(
            "UPDATE desktop_workers SET vnc_password_text = "
            "pgp_sym_decrypt(vnc_password, current_setting('app.encryption_key', true)) "
            "WHERE vnc_password IS NOT NULL"
        )
    )
    op.drop_column('desktop_workers', 'vnc_password')
    op.alter_column('desktop_workers', 'vnc_password_text', new_column_name='vnc_password')

    op.drop_table('figaro_settings')
