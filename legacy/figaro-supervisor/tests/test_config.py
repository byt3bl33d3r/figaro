"""Tests for figaro_supervisor.config module."""

import os
import socket
from unittest.mock import patch

from figaro_supervisor.config import Settings


class TestSettings:
    """Tests for the Settings class."""

    def test_default_values(self):
        """Test that defaults are set correctly when no env vars provided."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        assert settings.nats_url == "nats://localhost:4222"
        assert settings.supervisor_id is None
        assert settings.heartbeat_interval == 30.0
        assert settings.model == "claude-opus-4-6"
        assert settings.max_turns is None

    def test_env_prefix(self):
        """Test that SUPERVISOR_ prefix is used for environment variables."""
        env = {
            "SUPERVISOR_NATS_URL": "nats://custom:4222",
            "SUPERVISOR_SUPERVISOR_ID": "test-supervisor-123",
            "SUPERVISOR_MODEL": "claude-opus-4-20250514",
            "SUPERVISOR_HEARTBEAT_INTERVAL": "60.0",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        assert settings.nats_url == "nats://custom:4222"
        assert settings.supervisor_id == "test-supervisor-123"
        assert settings.model == "claude-opus-4-20250514"
        assert settings.heartbeat_interval == 60.0

    def test_get_supervisor_id_returns_configured(self):
        """Test get_supervisor_id returns configured ID when set."""
        env = {"SUPERVISOR_SUPERVISOR_ID": "my-supervisor"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        assert settings.get_supervisor_id() == "my-supervisor"

    def test_get_supervisor_id_falls_back_to_hostname(self):
        """Test get_supervisor_id returns hostname when not configured."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        supervisor_id = settings.get_supervisor_id()
        assert supervisor_id == socket.gethostname()

    def test_max_turns_optional(self):
        """Test max_turns can be set or left as None."""
        env = {"SUPERVISOR_MAX_TURNS": "10"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        assert settings.max_turns == 10
