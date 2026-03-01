"""Tests for patchright_cli.client module."""

from __future__ import annotations

import json
import signal
import socket
import subprocess
from unittest.mock import MagicMock, patch

from patchright_cli.client import (
    _receive_all,
    close_all_sessions,
    delete_session_data,
    kill_all_sessions,
    open_session,
    send_command,
    start_daemon,
)


# ---------------------------------------------------------------------------
# _receive_all
# ---------------------------------------------------------------------------


class TestReceiveAll:
    """Tests for the _receive_all helper that reads newline-delimited data."""

    def test_single_chunk_with_newline(self):
        """A single recv returning data ending with newline should return stripped data."""
        mock_sock = MagicMock(spec=socket.socket)
        payload = b'{"ok": true}\n'
        mock_sock.recv.return_value = payload

        result = _receive_all(mock_sock)

        assert result == b'{"ok": true}'
        mock_sock.recv.assert_called_once_with(65536)

    def test_multiple_chunks_before_newline(self):
        """Multiple recv calls should be concatenated until newline appears."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.side_effect = [
            b'{"ok": ',
            b'true, "data": "hello"}\n',
        ]

        result = _receive_all(mock_sock)

        assert result == b'{"ok": true, "data": "hello"}'
        assert mock_sock.recv.call_count == 2

    def test_empty_recv_connection_closed(self):
        """When recv returns empty bytes (connection closed), return accumulated data."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b""

        result = _receive_all(mock_sock)

        assert result == b""
        mock_sock.recv.assert_called_once_with(65536)


# ---------------------------------------------------------------------------
# send_command
# ---------------------------------------------------------------------------


class TestSendCommand:
    """Tests for send_command which communicates with a daemon via Unix socket."""

    def test_socket_does_not_exist(self, sessions_dir):
        """When the socket file doesn't exist, return an error dict."""
        result = send_command("nonexistent", "snapshot")

        assert result["ok"] is False
        assert "not running" in result["error"]
        assert "nonexistent" in result["error"]

    def test_success(self, sessions_dir):
        """A successful command should send JSON and return parsed response."""
        session_name = "test-session"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        response_data = {"ok": True, "output": "snapshot taken"}
        response_bytes = json.dumps(response_data).encode() + b"\n"

        mock_sock_instance = MagicMock(spec=socket.socket)
        mock_sock_instance.recv.return_value = response_bytes

        with patch(
            "patchright_cli.client.socket.socket", return_value=mock_sock_instance
        ):
            result = send_command(session_name, "snapshot", {"ref": "e0"})

        assert result == response_data

        mock_sock_instance.settimeout.assert_called_once_with(120.0)
        mock_sock_instance.connect.assert_called_once_with(str(sock_path))

        sent_payload = mock_sock_instance.sendall.call_args[0][0]
        sent_data = json.loads(sent_payload.decode().strip())
        assert sent_data == {"cmd": "snapshot", "args": {"ref": "e0"}}

        mock_sock_instance.close.assert_called_once()

    def test_connection_refused_error(self, sessions_dir):
        """ConnectionRefusedError should clean up session and return error."""
        session_name = "stale-session"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        mock_sock_instance = MagicMock(spec=socket.socket)
        mock_sock_instance.connect.side_effect = ConnectionRefusedError("refused")

        with (
            patch(
                "patchright_cli.client.socket.socket", return_value=mock_sock_instance
            ),
            patch("patchright_cli.client.cleanup_session") as mock_cleanup,
        ):
            result = send_command(session_name, "snapshot")

        assert result["ok"] is False
        assert "not responding" in result["error"]
        mock_cleanup.assert_called_once_with(session_name)
        mock_sock_instance.close.assert_called_once()

    def test_socket_timeout(self, sessions_dir):
        """socket.timeout should return a timeout error."""
        session_name = "slow-session"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        mock_sock_instance = MagicMock(spec=socket.socket)
        mock_sock_instance.connect.return_value = None
        mock_sock_instance.sendall.return_value = None
        mock_sock_instance.recv.side_effect = socket.timeout("timed out")

        with patch(
            "patchright_cli.client.socket.socket", return_value=mock_sock_instance
        ):
            result = send_command(session_name, "navigate", timeout=30.0)

        assert result["ok"] is False
        assert "timed out" in result["error"].lower()
        assert "30.0" in result["error"]
        mock_sock_instance.close.assert_called_once()

    def test_generic_exception(self, sessions_dir):
        """An unexpected exception should return a connection error."""
        session_name = "broken-session"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        mock_sock_instance = MagicMock(spec=socket.socket)
        mock_sock_instance.connect.side_effect = OSError("some OS error")

        with patch(
            "patchright_cli.client.socket.socket", return_value=mock_sock_instance
        ):
            result = send_command(session_name, "click")

        assert result["ok"] is False
        assert "Connection error" in result["error"]
        assert "some OS error" in result["error"]
        mock_sock_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# start_daemon
# ---------------------------------------------------------------------------


class TestStartDaemon:
    """Tests for start_daemon which spawns the browser daemon process."""

    def test_already_running(self, sessions_dir, config_dict):
        """If the socket exists and session is alive, return True immediately."""
        session_name = "running"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        with patch("patchright_cli.client.is_session_alive", return_value=True):
            result = start_daemon(session_name, config_dict)

        assert result is True

    def test_stale_socket_cleaned_up(self, sessions_dir, config_dict):
        """A stale socket (exists but not alive) should be cleaned up before spawning."""
        session_name = "stale"
        sock_path = sessions_dir / session_name / "server.sock"
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        mock_proc = MagicMock(spec=subprocess.Popen)
        # Process alive on first check, then socket appears
        mock_proc.poll.return_value = None

        def create_socket_on_poll():
            """Simulate the daemon creating the socket file after cleanup."""
            sock_path.touch()
            return None

        with (
            patch("patchright_cli.client.is_session_alive", return_value=False),
            patch("patchright_cli.client.cleanup_session") as mock_cleanup,
            patch("patchright_cli.client.subprocess.Popen", return_value=mock_proc),
            patch("patchright_cli.client.time.sleep"),
        ):
            # After cleanup, socket is removed; re-create it to simulate daemon starting
            def side_effect_cleanup(name):
                sock_path.unlink(missing_ok=True)

            mock_cleanup.side_effect = side_effect_cleanup

            # On the second poll check the socket appears
            poll_count = 0

            def poll_side_effect():
                nonlocal poll_count
                poll_count += 1
                if poll_count >= 2:
                    sock_path.touch()
                return None

            mock_proc.poll.side_effect = poll_side_effect

            result = start_daemon(session_name, config_dict)

        assert result is True
        mock_cleanup.assert_called_once_with(session_name)

    def test_success_spawns_process(self, sessions_dir, config_dict):
        """A successful start should spawn Popen and wait for socket to appear."""
        session_name = "new-session"

        mock_proc = MagicMock(spec=subprocess.Popen)
        poll_count = 0

        def poll_side_effect():
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 2:
                # Simulate daemon creating the socket
                sock_path = sessions_dir / session_name / "server.sock"
                sock_path.parent.mkdir(parents=True, exist_ok=True)
                sock_path.touch()
            return None

        mock_proc.poll.side_effect = poll_side_effect

        with (
            patch(
                "patchright_cli.client.subprocess.Popen", return_value=mock_proc
            ) as mock_popen,
            patch("patchright_cli.client.time.sleep"),
        ):
            result = start_daemon(session_name, config_dict)

        assert result is True
        mock_popen.assert_called_once()
        popen_kwargs = mock_popen.call_args
        assert popen_kwargs.kwargs["start_new_session"] is True
        assert popen_kwargs.kwargs["stdout"] == subprocess.DEVNULL
        assert popen_kwargs.kwargs["stderr"] == subprocess.DEVNULL

    def test_process_dies_immediately(self, sessions_dir, config_dict):
        """If the spawned process exits immediately (poll != None), return False."""
        session_name = "doomed"

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 1  # Process already exited with code 1

        with (
            patch("patchright_cli.client.subprocess.Popen", return_value=mock_proc),
            patch("patchright_cli.client.time.sleep"),
        ):
            result = start_daemon(session_name, config_dict)

        assert result is False

    def test_timeout_socket_never_appears(self, sessions_dir, config_dict):
        """If the socket never appears within timeout, return False."""
        session_name = "timeout-session"

        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None  # Process stays alive but no socket

        call_count = 0

        def advancing_monotonic():
            """Simulate time advancing past the timeout."""
            nonlocal call_count
            call_count += 1
            # First call establishes start_time, subsequent calls advance time
            return call_count * 5.0

        with (
            patch("patchright_cli.client.subprocess.Popen", return_value=mock_proc),
            patch(
                "patchright_cli.client.time.monotonic", side_effect=advancing_monotonic
            ),
            patch("patchright_cli.client.time.sleep"),
        ):
            result = start_daemon(session_name, config_dict, timeout=10.0)

        assert result is False


# ---------------------------------------------------------------------------
# open_session
# ---------------------------------------------------------------------------


class TestOpenSession:
    """Tests for open_session which starts daemon and sends the open command."""

    def test_success(self, sessions_dir, config_dict):
        """Successful open: start_daemon returns True, send_command returns result."""
        expected = {"ok": True, "output": "Browser opened"}

        with (
            patch("patchright_cli.client.start_daemon", return_value=True),
            patch(
                "patchright_cli.client.send_command", return_value=expected
            ) as mock_send,
        ):
            result = open_session("my-session", config_dict)

        assert result == expected
        mock_send.assert_called_once_with("my-session", "open", {})

    def test_daemon_fails_to_start(self, sessions_dir, config_dict):
        """When start_daemon returns False, return an error without sending commands."""
        with (
            patch("patchright_cli.client.start_daemon", return_value=False),
            patch("patchright_cli.client.send_command") as mock_send,
        ):
            result = open_session("bad-session", config_dict)

        assert result["ok"] is False
        assert "Failed to start" in result["error"]
        mock_send.assert_not_called()

    def test_with_url_parameter(self, sessions_dir, config_dict):
        """When a url is provided, it should be included in args to send_command."""
        expected = {"ok": True, "output": "Navigated"}

        with (
            patch("patchright_cli.client.start_daemon", return_value=True),
            patch(
                "patchright_cli.client.send_command", return_value=expected
            ) as mock_send,
        ):
            result = open_session("nav-session", config_dict, url="https://example.com")

        assert result == expected
        mock_send.assert_called_once_with(
            "nav-session", "open", {"url": "https://example.com"}
        )


# ---------------------------------------------------------------------------
# close_all_sessions
# ---------------------------------------------------------------------------


class TestCloseAllSessions:
    """Tests for close_all_sessions which gracefully closes running daemons."""

    def test_mixed_alive_and_dead_sessions(self, sessions_dir):
        """Alive sessions get 'close' command; dead sessions get cleaned up."""
        sessions = [
            {"name": "alive-1", "alive": True, "pid": 1001},
            {"name": "dead-1", "alive": False, "pid": 2001},
            {"name": "alive-2", "alive": True, "pid": 1002},
        ]

        with (
            patch("patchright_cli.client.list_sessions", return_value=sessions),
            patch(
                "patchright_cli.client.send_command",
                return_value={"ok": True, "output": "closed"},
            ) as mock_send,
            patch("patchright_cli.client.cleanup_session") as mock_cleanup,
        ):
            results = close_all_sessions()

        assert len(results) == 3

        # Alive sessions should have send_command called
        assert mock_send.call_count == 2
        mock_send.assert_any_call("alive-1", "close")
        mock_send.assert_any_call("alive-2", "close")

        # Dead session should be cleaned up
        mock_cleanup.assert_called_once_with("dead-1")

        # Check result structure for the dead session
        dead_result = [r for r in results if r["name"] == "dead-1"][0]
        assert dead_result["ok"] is True
        assert "stale" in dead_result["output"].lower()


# ---------------------------------------------------------------------------
# kill_all_sessions
# ---------------------------------------------------------------------------


class TestKillAllSessions:
    """Tests for kill_all_sessions which forcefully terminates daemons."""

    def test_sigterm_success(self, sessions_dir):
        """Alive sessions with PIDs should be sent SIGTERM and cleaned up."""
        sessions = [
            {"name": "worker-1", "alive": True, "pid": 5001},
            {"name": "worker-2", "alive": True, "pid": 5002},
        ]

        with (
            patch("patchright_cli.client.list_sessions", return_value=sessions),
            patch("patchright_cli.client.os.kill") as mock_kill,
            patch("patchright_cli.client.cleanup_session") as mock_cleanup,
        ):
            results = kill_all_sessions()

        assert len(results) == 2
        assert all(r["ok"] is True for r in results)
        assert "5001" in results[0]["output"]
        assert "5002" in results[1]["output"]

        mock_kill.assert_any_call(5001, signal.SIGTERM)
        mock_kill.assert_any_call(5002, signal.SIGTERM)

        # cleanup_session called for every session regardless
        assert mock_cleanup.call_count == 2
        mock_cleanup.assert_any_call("worker-1")
        mock_cleanup.assert_any_call("worker-2")

    def test_process_lookup_and_permission_errors(self, sessions_dir):
        """ProcessLookupError should report 'Already dead'; PermissionError should report failure."""
        sessions = [
            {"name": "gone", "alive": True, "pid": 6001},
            {"name": "protected", "alive": True, "pid": 6002},
            {"name": "no-pid", "alive": False, "pid": None},
        ]

        def kill_side_effect(pid, sig):
            if pid == 6001:
                raise ProcessLookupError()
            if pid == 6002:
                raise PermissionError("not permitted")

        with (
            patch("patchright_cli.client.list_sessions", return_value=sessions),
            patch("patchright_cli.client.os.kill", side_effect=kill_side_effect),
            patch("patchright_cli.client.cleanup_session") as mock_cleanup,
        ):
            results = kill_all_sessions()

        assert (
            len(results) == 2
        )  # no-pid session has no pid and not alive => no result appended

        gone_result = [r for r in results if r["name"] == "gone"][0]
        assert gone_result["ok"] is True
        assert "dead" in gone_result["output"].lower()

        protected_result = [r for r in results if r["name"] == "protected"][0]
        assert protected_result["ok"] is False
        assert "Permission denied" in protected_result["error"]

        # cleanup_session is called for all sessions
        assert mock_cleanup.call_count == 3
        mock_cleanup.assert_any_call("gone")
        mock_cleanup.assert_any_call("protected")
        mock_cleanup.assert_any_call("no-pid")


# ---------------------------------------------------------------------------
# delete_session_data
# ---------------------------------------------------------------------------


class TestDeleteSessionData:
    """Tests for delete_session_data which removes the session directory."""

    def test_success(self, sessions_dir):
        """When session is not alive and rmtree succeeds, return success."""
        session_name = "old-session"
        session_dir = sessions_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "config.json").write_text("{}", encoding="utf-8")

        with (
            patch("patchright_cli.client.is_session_alive", return_value=False),
            patch("patchright_cli.client.shutil.rmtree") as mock_rmtree,
        ):
            result = delete_session_data(session_name)

        assert result["ok"] is True
        assert session_name in result["output"]
        mock_rmtree.assert_called_once()

    def test_still_running(self, sessions_dir):
        """When session is still alive, return error without deleting."""
        session_name = "active-session"

        with patch("patchright_cli.client.is_session_alive", return_value=True):
            result = delete_session_data(session_name)

        assert result["ok"] is False
        assert "still running" in result["error"]

    def test_rmtree_raises_exception(self, sessions_dir):
        """When rmtree fails, return the error message."""
        session_name = "corrupted-session"

        with (
            patch("patchright_cli.client.is_session_alive", return_value=False),
            patch(
                "patchright_cli.client.shutil.rmtree",
                side_effect=PermissionError("cannot delete"),
            ),
        ):
            result = delete_session_data(session_name)

        assert result["ok"] is False
        assert "cannot delete" in result["error"]
