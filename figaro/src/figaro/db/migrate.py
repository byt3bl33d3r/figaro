"""Programmatic Alembic migration runner.

Works both in development (with alembic.ini) and when installed as a package.
"""

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

INITIAL_REVISION = "30b18e453168"


def get_alembic_config() -> Config:
    migrations_dir = str(Path(__file__).parent / "migrations")
    cfg = Config()
    cfg.set_main_option("script_location", migrations_dir)

    db_url = os.environ.get("FIGARO_DATABASE_URL", "")
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url)

    return cfg


def upgrade(revision: str = "head") -> None:
    cfg = get_alembic_config()
    try:
        command.upgrade(cfg, revision)
    except Exception as e:
        if "already exists" in str(e):
            # Database has existing tables but no alembic_version tracking
            # (e.g. created before Alembic was introduced). Stamp the initial
            # revision as applied, then upgrade remaining migrations.
            logger.warning(
                "Tables already exist without alembic_version tracking. "
                "Stamping initial revision %s and retrying.",
                INITIAL_REVISION,
            )
            command.stamp(cfg, INITIAL_REVISION)
            command.upgrade(cfg, revision)
        else:
            raise


def main() -> None:
    upgrade()
