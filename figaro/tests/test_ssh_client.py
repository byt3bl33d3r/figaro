"""Tests for the SSH client utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

from figaro.services.ssh_client import parse_ssh_url, run_command


class TestParseSshUrl:
    """Tests for parse_ssh_url()."""

    def test_ssh_scheme_with_port(self):
        host, port, user, pw = parse_ssh_url("ssh://myhost:2222")
        assert host == "myhost"
        assert port == 2222
        assert user is None
        assert pw is None

    def test_ssh_scheme_default_port(self):
        host, port, user, pw = parse_ssh_url("ssh://myhost")
        assert host == "myhost"
        assert port == 22

    def test_credentials_extracted(self):
        host, port, user, pw = parse_ssh_url("ssh://admin:secret@myhost:22")
        assert host == "myhost"
        assert port == 22
        assert user == "admin"
        assert pw == "secret"

    def test_custom_default_port(self):
        host, port, _, _ = parse_ssh_url("other://myhost", default_port=2222)
        assert port == 2222

    def test_empty_url_defaults(self):
        host, port, user, pw = parse_ssh_url("")
        assert host == "localhost"
        assert port == 22
        assert user is None
        assert pw is None

    def test_no_password(self):
        host, port, user, pw = parse_ssh_url("ssh://admin@myhost")
        assert user == "admin"
        assert pw is None


class TestRunCommand:
    """Tests for run_command()."""

    async def test_returns_stdout_stderr_exit_code(self):
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm):
            result = await run_command("host", 22, "user", "pass", "echo hello")

        assert result["stdout"] == "hello\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    async def test_timeout_passed_to_run(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm):
            await run_command("host", 22, "user", "pass", "sleep 5", timeout=60.0)

        mock_conn.run.assert_awaited_once_with("sleep 5", timeout=60.0)

    async def test_connect_called_with_correct_params(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm) as mock_connect:
            await run_command("myhost", 2222, "admin", "secret", "ls")

        mock_connect.assert_called_once_with(
            "myhost", port=2222, username="admin", password="secret", known_hosts=None
        )

    async def test_stderr_output(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "error occurred\n"
        mock_result.exit_status = 1

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm):
            result = await run_command("host", 22, "user", "pass", "bad_cmd")

        assert result["stderr"] == "error occurred\n"
        assert result["exit_code"] == 1

    async def test_none_exit_status(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_status = None

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm):
            result = await run_command("host", 22, None, None, "cmd")

        assert result["exit_code"] == -1

    async def test_none_stdout_stderr(self):
        mock_result = MagicMock()
        mock_result.stdout = None
        mock_result.stderr = None
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("figaro.services.ssh_client.asyncssh.connect", return_value=cm):
            result = await run_command("host", 22, "user", "pass", "cmd")

        assert result["stdout"] == ""
        assert result["stderr"] == ""
