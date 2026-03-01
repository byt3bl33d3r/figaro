"""Tests for patchright_cli.session module."""

from __future__ import annotations

import json
import os

from patchright_cli.session import (
    cleanup_session,
    generate_output_filename,
    get_config_path,
    get_log_path,
    get_output_dir,
    get_pid_path,
    get_session_dir,
    get_sessions_dir,
    get_socket_path,
    is_session_alive,
    list_sessions,
    read_pid,
    read_session_config,
    resolve_session_name,
    write_pid,
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


class TestGetSessionsDir:
    def test_creates_and_returns_correct_path(self, sessions_dir):
        result = get_sessions_dir()
        assert result == sessions_dir
        assert result.exists()
        assert result.is_dir()

    def test_idempotent_on_existing_dir(self, sessions_dir):
        # Call twice; both should succeed and return the same path.
        first = get_sessions_dir()
        second = get_sessions_dir()
        assert first == second
        assert first.exists()


class TestGetSessionDir:
    def test_creates_and_returns_correct_path(self, sessions_dir):
        result = get_session_dir("my-session")
        assert result == sessions_dir / "my-session"
        assert result.exists()
        assert result.is_dir()

    def test_creates_nested_under_sessions_dir(self, sessions_dir):
        result = get_session_dir("another")
        assert result.parent == sessions_dir


class TestGetSocketPath:
    def test_returns_correct_path(self, sessions_dir):
        result = get_socket_path("demo")
        assert result == sessions_dir / "demo" / "server.sock"
        assert result.name == "server.sock"


class TestGetPidPath:
    def test_returns_correct_path(self, sessions_dir):
        result = get_pid_path("demo")
        assert result == sessions_dir / "demo" / "pid"
        assert result.name == "pid"


class TestGetLogPath:
    def test_returns_correct_path(self, sessions_dir):
        result = get_log_path("demo")
        assert result == sessions_dir / "demo" / "daemon.log"
        assert result.name == "daemon.log"


class TestGetConfigPath:
    def test_returns_correct_path(self, sessions_dir):
        result = get_config_path("demo")
        assert result == sessions_dir / "demo" / "config.json"
        assert result.name == "config.json"


class TestReadSessionConfig:
    def test_returns_dict_for_valid_config(self, sessions_dir):
        config = {"browser": {"browser_name": "chromium"}}
        config_path = get_config_path("with-config")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = read_session_config("with-config")
        assert result == config

    def test_returns_none_for_missing_file(self, sessions_dir):
        get_session_dir("no-config")
        assert read_session_config("no-config") is None

    def test_returns_none_for_invalid_json(self, sessions_dir):
        config_path = get_config_path("bad-json")
        config_path.write_text("not valid json {{{", encoding="utf-8")
        assert read_session_config("bad-json") is None


# ---------------------------------------------------------------------------
# PID operations
# ---------------------------------------------------------------------------


class TestWritePid:
    def test_writes_correct_content(self, sessions_dir):
        write_pid("sess", 12345)
        pid_path = get_pid_path("sess")
        assert pid_path.read_text(encoding="utf-8") == "12345"

    def test_overwrites_existing_pid(self, sessions_dir):
        write_pid("sess", 111)
        write_pid("sess", 222)
        assert read_pid("sess") == 222


class TestReadPid:
    def test_returns_int_for_valid_file(self, sessions_dir):
        write_pid("sess", 42)
        assert read_pid("sess") == 42

    def test_returns_none_for_missing_file(self, sessions_dir):
        # Session dir exists but no pid file written.
        get_session_dir("no-pid")
        assert read_pid("no-pid") is None

    def test_returns_none_for_empty_file(self, sessions_dir):
        pid_path = get_pid_path("empty-pid")
        pid_path.write_text("", encoding="utf-8")
        assert read_pid("empty-pid") is None

    def test_returns_none_for_non_integer_content(self, sessions_dir):
        pid_path = get_pid_path("bad-pid")
        pid_path.write_text("not-a-number", encoding="utf-8")
        assert read_pid("bad-pid") is None

    def test_returns_none_for_whitespace_only(self, sessions_dir):
        pid_path = get_pid_path("ws-pid")
        pid_path.write_text("   \n  ", encoding="utf-8")
        assert read_pid("ws-pid") is None


# ---------------------------------------------------------------------------
# is_session_alive
# ---------------------------------------------------------------------------


class TestIsSessionAlive:
    def test_alive_process(self, sessions_dir, monkeypatch):
        write_pid("alive", 9999)
        # os.kill with signal 0 succeeds silently when process exists.
        monkeypatch.setattr(os, "kill", lambda pid, sig: None)
        assert is_session_alive("alive") is True

    def test_dead_process(self, sessions_dir, monkeypatch):
        write_pid("dead", 9999)

        def fake_kill(pid, sig):
            raise ProcessLookupError("No such process")

        monkeypatch.setattr(os, "kill", fake_kill)
        assert is_session_alive("dead") is False

    def test_permission_error_returns_true(self, sessions_dir, monkeypatch):
        write_pid("perm", 9999)

        def fake_kill(pid, sig):
            raise PermissionError("Operation not permitted")

        monkeypatch.setattr(os, "kill", fake_kill)
        assert is_session_alive("perm") is True

    def test_no_pid_file_returns_false(self, sessions_dir):
        # Session directory exists but there is no pid file.
        get_session_dir("no-pid")
        assert is_session_alive("no-pid") is False


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_empty_dir_returns_empty_list(self, sessions_dir):
        result = list_sessions()
        assert result == []

    def test_populated_dir_returns_correct_entries(self, sessions_dir, monkeypatch):
        # Create two sessions with PIDs.
        write_pid("alpha", 100)
        write_pid("beta", 200)

        # Mock os.kill: alpha is alive, beta is dead.
        def fake_kill(pid, sig):
            if pid == 200:
                raise ProcessLookupError("No such process")

        monkeypatch.setattr(os, "kill", fake_kill)

        result = list_sessions()
        assert len(result) == 2

        # Results should be sorted by name.
        assert result[0]["name"] == "alpha"
        assert result[0]["alive"] is True
        assert result[0]["pid"] == 100
        assert result[0]["config"] is None  # no config.json written

        assert result[1]["name"] == "beta"
        assert result[1]["alive"] is False
        assert result[1]["pid"] == 200
        assert result[1]["config"] is None

    def test_skips_regular_files(self, sessions_dir, monkeypatch):
        # Create a session directory and a stray regular file.
        write_pid("real-session", 300)
        monkeypatch.setattr(os, "kill", lambda pid, sig: None)

        # Ensure the sessions dir itself exists, then put a file in it.
        stray_file = get_sessions_dir() / "not-a-directory"
        stray_file.write_text("junk", encoding="utf-8")

        result = list_sessions()
        names = [entry["name"] for entry in result]
        assert "real-session" in names
        assert "not-a-directory" not in names

    def test_session_without_pid_file(self, sessions_dir, monkeypatch):
        # A session directory with no pid file should show pid=None, alive=False.
        get_session_dir("empty-session")
        result = list_sessions()
        assert len(result) == 1
        assert result[0]["name"] == "empty-session"
        assert result[0]["pid"] is None
        assert result[0]["alive"] is False
        assert result[0]["config"] is None

    def test_includes_config_when_present(self, sessions_dir, monkeypatch):
        # Create a session with both a PID and a config.json.
        write_pid("configured", 400)
        config_data = {"browser": {"browser_name": "firefox"}}
        config_path = get_config_path("configured")
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        monkeypatch.setattr(os, "kill", lambda pid, sig: None)

        result = list_sessions()
        assert len(result) == 1
        assert result[0]["name"] == "configured"
        assert result[0]["config"] == config_data


# ---------------------------------------------------------------------------
# cleanup_session
# ---------------------------------------------------------------------------


class TestCleanupSession:
    def test_removes_socket_and_pid_files(self, sessions_dir):
        write_pid("cleanup-me", 555)
        socket_path = get_socket_path("cleanup-me")
        socket_path.write_text("fake-socket", encoding="utf-8")

        # Both files exist before cleanup.
        assert get_pid_path("cleanup-me").exists()
        assert socket_path.exists()

        cleanup_session("cleanup-me")

        assert not get_pid_path("cleanup-me").exists()
        assert not socket_path.exists()

    def test_survives_if_files_already_missing(self, sessions_dir):
        # Create the session dir but no runtime files.
        get_session_dir("already-clean")
        # Should not raise.
        cleanup_session("already-clean")

    def test_preserves_other_files(self, sessions_dir):
        write_pid("has-config", 777)
        config_path = get_session_dir("has-config") / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        cleanup_session("has-config")

        # config.json should still be present.
        assert config_path.exists()
        # The session directory should still exist.
        assert get_session_dir("has-config").exists()


# ---------------------------------------------------------------------------
# resolve_session_name
# ---------------------------------------------------------------------------


class TestResolveSessionName:
    def test_cli_arg_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "from-env")
        assert resolve_session_name("from-cli") == "from-cli"

    def test_env_var_used_when_no_cli_arg(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "env-session")
        assert resolve_session_name(None) == "env-session"

    def test_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("PLAYWRIGHT_CLI_SESSION", raising=False)
        assert resolve_session_name(None) == "default"

    def test_empty_string_cli_arg_uses_env(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "env-session")
        assert resolve_session_name("") == "env-session"

    def test_empty_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "")
        assert resolve_session_name(None) == "default"

    def test_whitespace_env_var_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "   ")
        assert resolve_session_name(None) == "default"


# ---------------------------------------------------------------------------
# Output directory & filenames
# ---------------------------------------------------------------------------


class TestGetOutputDir:
    def test_creates_and_returns_correct_path(self, output_dir):
        result = get_output_dir()
        assert result == output_dir
        assert result.exists()
        assert result.is_dir()

    def test_idempotent_on_existing_dir(self, output_dir):
        first = get_output_dir()
        second = get_output_dir()
        assert first == second


class TestGenerateOutputFilename:
    def test_returns_path_with_correct_prefix_and_extension(self, output_dir):
        path = generate_output_filename("screenshot", "png")
        assert path.name.startswith("screenshot-")
        assert path.name.endswith(".png")

    def test_path_is_under_output_dir(self, output_dir):
        path = generate_output_filename("page", "yml")
        assert path.parent == output_dir

    def test_different_prefixes_produce_different_names(self, output_dir):
        path_a = generate_output_filename("trace", "zip")
        path_b = generate_output_filename("screenshot", "png")
        assert path_a.name != path_b.name

    def test_timestamp_has_no_colons(self, output_dir):
        # Colons are replaced with dashes for filesystem compatibility.
        path = generate_output_filename("snap", "yml")
        # The stem is everything before the last dot (extension).
        assert ":" not in path.stem
