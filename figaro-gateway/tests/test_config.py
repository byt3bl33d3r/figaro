"""Tests for gateway configuration."""

import os
from unittest.mock import patch

from figaro_gateway.config import Settings


class TestSettings:
    def test_defaults(self):
        """Test default settings values."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        assert settings.nats_url == "nats://localhost:4222"
        assert settings.telegram_bot_token is None
        assert settings.telegram_allowed_chat_ids == []

    def test_env_prefix(self):
        """Test settings load from GATEWAY_ prefixed env vars."""
        env = {
            "GATEWAY_NATS_URL": "nats://custom:4222",
            "GATEWAY_TELEGRAM_BOT_TOKEN": "test-token-123",
            "GATEWAY_TELEGRAM_ALLOWED_CHAT_IDS": "[111, 222]",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
        assert settings.nats_url == "nats://custom:4222"
        assert settings.telegram_bot_token == "test-token-123"
        assert settings.telegram_allowed_chat_ids == [111, 222]

    def test_partial_env(self):
        """Test settings with only some env vars set."""
        env = {
            "GATEWAY_TELEGRAM_BOT_TOKEN": "my-token",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
        assert settings.telegram_bot_token == "my-token"
        assert settings.nats_url == "nats://localhost:4222"
