"""Tests for the config module."""

from unittest.mock import patch

from figaro_worker.config import Settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test default configuration values."""
        settings = Settings()

        assert settings.nats_url == "nats://localhost:4222"
        assert settings.heartbeat_interval == 30.0
        assert settings.reconnect_delay == 1.0
        assert settings.max_reconnect_delay == 60.0
        assert settings.novnc_port == 6080

    def test_get_worker_id_from_setting(self):
        """Test get_worker_id returns configured ID."""
        settings = Settings(worker_id="my-worker")
        assert settings.get_worker_id() == "my-worker"

    def test_get_worker_id_falls_back_to_hostname(self):
        """Test get_worker_id returns hostname if not configured."""
        settings = Settings(worker_id=None)

        with patch("figaro_worker.config.socket.gethostname", return_value="myhost"):
            assert settings.get_worker_id() == "myhost"

    def test_get_novnc_url_from_setting(self):
        """Test get_novnc_url returns configured URL."""
        settings = Settings(novnc_url="ws://custom:5000/vnc")
        assert settings.get_novnc_url() == "ws://custom:5000/vnc"

    def test_get_novnc_url_auto_detect(self):
        """Test get_novnc_url auto-detects hostname."""
        settings = Settings(novnc_url=None, novnc_port=6080)

        with patch("figaro_worker.config.socket.gethostname", return_value="myhost"):
            url = settings.get_novnc_url()

        assert url == "ws://myhost:6080/websockify"

    def test_env_prefix(self):
        """Test that environment variables use WORKER_ prefix."""
        with patch.dict("os.environ", {
            "WORKER_NATS_URL": "nats://custom:4222",
            "WORKER_WORKER_ID": "env-worker",
        }):
            settings = Settings()
            assert settings.nats_url == "nats://custom:4222"
            # Note: pydantic-settings loads from env on construction
