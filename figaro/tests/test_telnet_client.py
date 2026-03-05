"""Tests for the Telnet client utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

from figaro.services.telnet_client import parse_telnet_url, run_command


class TestParseTelnetUrl:
    """Tests for parse_telnet_url()."""

    def test_telnet_scheme_with_port(self):
        host, port, user, pw = parse_telnet_url("telnet://myhost:2323")
        assert host == "myhost"
        assert port == 2323
        assert user is None
        assert pw is None

    def test_telnet_scheme_default_port(self):
        host, port, user, pw = parse_telnet_url("telnet://myhost")
        assert host == "myhost"
        assert port == 23

    def test_credentials_extracted(self):
        host, port, user, pw = parse_telnet_url("telnet://admin:secret@myhost:23")
        assert host == "myhost"
        assert port == 23
        assert user == "admin"
        assert pw == "secret"

    def test_custom_default_port(self):
        host, port, _, _ = parse_telnet_url("other://myhost", default_port=2323)
        assert port == 2323

    def test_empty_url_defaults(self):
        host, port, user, pw = parse_telnet_url("")
        assert host == "localhost"
        assert port == 23
        assert user is None
        assert pw is None

    def test_no_password(self):
        host, port, user, pw = parse_telnet_url("telnet://admin@myhost")
        assert user == "admin"
        assert pw is None


class TestRunCommand:
    """Tests for run_command()."""

    async def test_command_without_login(self):
        """Running a command without credentials skips login sequence."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.close = MagicMock()

        # First read returns output, second read returns empty (EOF)
        mock_reader.read = AsyncMock(side_effect=[
            "file1.txt\nfile2.txt\n",
            "",
        ])

        with patch("figaro.services.telnet_client.telnetlib3.open_connection",
                   AsyncMock(return_value=(mock_reader, mock_writer))):
            result = await run_command("host", 23, None, None, "ls", timeout=5.0)

        assert "file1.txt" in result["output"]
        mock_writer.write.assert_called_once_with("ls\n")

    async def test_command_with_login(self):
        """Running a command with credentials performs login sequence."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.close = MagicMock()

        # Reads: login prompt, password prompt, post-login prompt, command output, EOF
        mock_reader.read = AsyncMock(side_effect=[
            "login: ",
            "Password: ",
            "Welcome\n$ ",
            "file1.txt\n",
            "",
        ])

        with patch("figaro.services.telnet_client.telnetlib3.open_connection",
                   AsyncMock(return_value=(mock_reader, mock_writer))):
            await run_command("host", 23, "admin", "secret", "ls", timeout=5.0)

        # Verify login sequence: username, password, command
        calls = mock_writer.write.call_args_list
        assert calls[0][0][0] == "admin\n"
        assert calls[1][0][0] == "secret\n"
        assert calls[2][0][0] == "ls\n"

    async def test_writer_closed_on_completion(self):
        """Writer is closed after command execution."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.close = MagicMock()

        mock_reader.read = AsyncMock(side_effect=["output\n", ""])

        with patch("figaro.services.telnet_client.telnetlib3.open_connection",
                   AsyncMock(return_value=(mock_reader, mock_writer))):
            await run_command("host", 23, None, None, "ls", timeout=5.0)

        mock_writer.close.assert_called_once()

    async def test_connect_params(self):
        """Verify open_connection is called with correct host and port."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.close = MagicMock()

        mock_reader.read = AsyncMock(side_effect=["output\n", ""])

        mock_open = AsyncMock(return_value=(mock_reader, mock_writer))
        with patch("figaro.services.telnet_client.telnetlib3.open_connection", mock_open):
            await run_command("myhost", 2323, None, None, "echo hi", timeout=5.0)

        mock_open.assert_awaited_once_with("myhost", 2323)
