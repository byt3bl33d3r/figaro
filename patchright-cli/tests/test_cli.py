"""Tests for patchright_cli.cli module."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from patchright_cli.cli import _args_to_dict, _register_subcommands, main
from patchright_cli.config import CLIConfig


# ---------------------------------------------------------------------------
# _args_to_dict
# ---------------------------------------------------------------------------


class TestArgsToDict:
    def test_excludes_session_config_command(self):
        """Keys 'session', 'config', and 'command' are stripped from the result."""
        ns = argparse.Namespace(
            session="my-session",
            config="/tmp/cfg.json",
            command="goto",
            url="https://example.com",
        )
        result = _args_to_dict(ns)
        assert result == {"url": "https://example.com"}
        assert "session" not in result
        assert "config" not in result
        assert "command" not in result

    def test_filters_none_values(self):
        """Keys whose value is None are excluded from the result."""
        ns = argparse.Namespace(
            session=None,
            config=None,
            command="screenshot",
            ref=None,
            filename="shot.png",
        )
        result = _args_to_dict(ns)
        assert result == {"filename": "shot.png"}
        assert "ref" not in result


# ---------------------------------------------------------------------------
# _register_subcommands
# ---------------------------------------------------------------------------


class TestRegisterSubcommands:
    def test_all_expected_commands_registered(self):
        """All documented subcommands must be present after registration."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        _register_subcommands(subparsers)

        expected_commands = {
            # Core
            "open",
            "goto",
            "close",
            "type",
            "click",
            "dblclick",
            "fill",
            "drag",
            "hover",
            "select",
            "upload",
            "check",
            "uncheck",
            "snapshot",
            "eval",
            "dialog-accept",
            "dialog-dismiss",
            "resize",
            # Navigation
            "go-back",
            "go-forward",
            "reload",
            # Keyboard
            "press",
            "keydown",
            "keyup",
            # Mouse
            "mousemove",
            "mousedown",
            "mouseup",
            "mousewheel",
            # Save as
            "screenshot",
            "pdf",
            # Tabs
            "tab-list",
            "tab-new",
            "tab-close",
            "tab-select",
            # Storage
            "state-save",
            "state-load",
            "cookie-list",
            "cookie-get",
            "cookie-set",
            "cookie-delete",
            "cookie-clear",
            "localstorage-list",
            "localstorage-get",
            "localstorage-set",
            "localstorage-delete",
            "localstorage-clear",
            "sessionstorage-list",
            "sessionstorage-get",
            "sessionstorage-set",
            "sessionstorage-delete",
            "sessionstorage-clear",
            # Network
            "route",
            "route-list",
            "unroute",
            # DevTools
            "console",
            "network",
            "tracing-start",
            "tracing-stop",
            "video-start",
            "video-stop",
            # Audio
            "transcribe-audio",
            # Session management
            "list",
            "close-all",
            "kill-all",
            "delete-data",
            "logs",
        }

        # _SubParsersAction stores parsers in its _name_parser_map attribute,
        # but the public way to check is via parser.parse_args.
        # Instead we iterate the subparsers choices dict.
        registered = set(subparsers.choices.keys())
        assert expected_commands.issubset(registered), (
            f"Missing commands: {expected_commands - registered}"
        )


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


class TestMainNoCommand:
    def test_no_command_exits_with_1(self):
        """Calling main() with no arguments prints help and exits 1."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


class TestMainList:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.list_sessions")
    def test_list_with_sessions(self, mock_list, _mock_config, capsys, sessions_dir):
        """The list command prints config info for populated sessions."""
        mock_list.return_value = [
            {
                "name": "default",
                "alive": True,
                "pid": 12345,
                "config": {
                    "browser": {
                        "browser_name": "chromium",
                        "isolated": False,
                        "user_data_dir": None,
                        "launch_options": {"headless": False},
                    }
                },
            },
            {"name": "other", "alive": False, "pid": None, "config": None},
        ]
        main(["list"])
        captured = capsys.readouterr()
        assert "### Browsers" in captured.out
        assert "default" in captured.out
        assert "open" in captured.out
        assert "other" in captured.out
        assert "closed" in captured.out
        # Config fields for the session with config
        assert "browser-type: chromium" in captured.out
        assert "user-data-dir:" in captured.out
        assert "headed: true" in captured.out
        # No config fields for the session without config
        lines = captured.out.splitlines()
        other_idx = next(i for i, line in enumerate(lines) if "other" in line)
        # After "other:" there should only be "status: closed", no browser-type
        other_lines = lines[other_idx:]
        assert not any("browser-type" in line for line in other_lines)

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.list_sessions")
    def test_list_no_sessions(self, mock_list, _mock_config, capsys, sessions_dir):
        """When there are no sessions, prints 'No sessions found.'."""
        mock_list.return_value = []
        main(["list"])
        captured = capsys.readouterr()
        assert "No sessions found." in captured.out


class TestMainCloseAll:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.close_all_sessions")
    def test_close_all(self, mock_close_all, _mock_config, capsys, sessions_dir):
        """close-all prints a status line for each session."""
        mock_close_all.return_value = [
            {"name": "s1", "ok": True},
            {"name": "s2", "ok": False, "error": "timeout"},
        ]
        main(["close-all"])
        captured = capsys.readouterr()
        assert "Closed session 's1'" in captured.out
        assert "Failed to close session 's2'" in captured.err
        assert "timeout" in captured.err


class TestMainKillAll:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.kill_all_sessions")
    def test_kill_all(self, mock_kill_all, _mock_config, capsys, sessions_dir):
        """kill-all prints a status line for each session."""
        mock_kill_all.return_value = [
            {"name": "s1", "ok": True, "output": "Killed PID 999"},
            {"name": "s2", "ok": False, "error": "Permission denied"},
        ]
        main(["kill-all"])
        captured = capsys.readouterr()
        assert "Killed PID 999" in captured.out
        assert "Failed to kill session 's2'" in captured.err
        assert "Permission denied" in captured.err


class TestMainDeleteData:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.delete_session_data")
    def test_delete_data_success(self, mock_delete, _mock_config, capsys, sessions_dir):
        """delete-data success prints the output message."""
        mock_delete.return_value = {
            "ok": True,
            "output": "Deleted data for session 'default'",
        }
        main(["delete-data"])
        captured = capsys.readouterr()
        assert "Deleted data" in captured.out

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.delete_session_data")
    def test_delete_data_failure(self, mock_delete, _mock_config, capsys, sessions_dir):
        """delete-data failure prints error to stderr and exits 1."""
        mock_delete.return_value = {"ok": False, "error": "Still running"}
        with pytest.raises(SystemExit) as exc_info:
            main(["delete-data"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Still running" in captured.err


class TestMainLogs:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    def test_logs_missing_file(self, _mock_config, capsys, sessions_dir):
        """logs with a missing log file prints an error and exits 1."""
        with pytest.raises(SystemExit) as exc_info:
            main(["logs"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No log file found" in captured.err

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    def test_logs_lines_zero_reads_full_file(self, _mock_config, capsys, sessions_dir):
        """logs --lines 0 reads the entire log file."""
        # Create the session dir and a log file
        session_dir = sessions_dir / "default"
        session_dir.mkdir(parents=True, exist_ok=True)
        log_file = session_dir / "daemon.log"
        log_content = "line1\nline2\nline3\n"
        log_file.write_text(log_content, encoding="utf-8")

        main(["logs", "--lines", "0"])
        captured = capsys.readouterr()
        assert "line1" in captured.out
        assert "line2" in captured.out
        assert "line3" in captured.out


class TestMainOpen:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_success(self, mock_open, _mock_config, capsys, sessions_dir):
        """open success prints the output message."""
        mock_open.return_value = {"ok": True, "output": "Session opened."}
        main(["open"])
        captured = capsys.readouterr()
        assert "Session opened." in captured.out
        mock_open.assert_called_once()
        # First arg is session name, second is config dict
        call_args = mock_open.call_args
        assert call_args[0][0] == "default"  # session name
        assert isinstance(call_args[0][1], dict)  # config dict

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_with_headed_flag(self, mock_open, mock_config, sessions_dir):
        """open --headed is accepted but is a no-op (headed is already the default)."""
        mock_open.return_value = {"ok": True, "output": "Session opened."}
        main(["open", "--headed"])
        call_args = mock_open.call_args
        config_dict = call_args[0][1]
        # headed is the default, so headless should remain False (no-op)
        assert config_dict["browser"]["launch_options"]["headless"] is False

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_with_browser_flag(self, mock_open, mock_config, sessions_dir):
        """open --browser chrome sets the browser channel in launch_options."""
        mock_open.return_value = {"ok": True, "output": "Session opened."}
        main(["open", "--browser", "chrome"])
        call_args = mock_open.call_args
        config_dict = call_args[0][1]
        assert config_dict["browser"]["launch_options"]["channel"] == "chrome"

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_with_isolated_flag(self, mock_open, mock_config, sessions_dir):
        """open --isolated sets isolated=True in the config."""
        mock_open.return_value = {"ok": True, "output": "Session opened."}
        main(["open", "--isolated"])
        call_args = mock_open.call_args
        config_dict = call_args[0][1]
        assert config_dict["browser"]["isolated"] is True

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_with_profile_flag(self, mock_open, mock_config, sessions_dir):
        """open --profile /my/dir sets user_data_dir in the config."""
        mock_open.return_value = {"ok": True, "output": "Session opened."}
        main(["open", "--profile", "/my/dir"])
        call_args = mock_open.call_args
        config_dict = call_args[0][1]
        assert config_dict["browser"]["user_data_dir"] == "/my/dir"

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.open_session")
    def test_open_failure(self, mock_open, _mock_config, capsys, sessions_dir):
        """open failure prints error to stderr and exits 1."""
        mock_open.return_value = {
            "ok": False,
            "error": "Failed to start browser daemon.",
        }
        with pytest.raises(SystemExit) as exc_info:
            main(["open"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Failed to start browser daemon." in captured.err


class TestMainInstall:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    def test_install_skills(self, _mock_config, capsys, sessions_dir, tmp_path):
        """install --skills copies skill dirs to ~/.claude/skills/."""
        from pathlib import Path

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        with patch.object(Path, "home", return_value=fake_home):
            main(["install", "--skills"])

        captured = capsys.readouterr()
        assert "Installed skill" in captured.out
        skill_dst = fake_home / ".claude" / "skills" / "patchright-cli"
        assert skill_dst.is_dir()
        assert (skill_dst / "SKILL.md").is_file()
        assert (skill_dst / "references").is_dir()

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    def test_install_without_skills(self, _mock_config, capsys, sessions_dir, tmp_path):
        """install without --skills creates .playwright directory."""
        import os

        os.chdir(tmp_path)
        main(["install"])
        captured = capsys.readouterr()
        assert "Workspace initialized at" in captured.out
        assert (tmp_path / ".playwright").is_dir()


class TestMainInstallBrowser:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("subprocess.run")
    def test_install_browser_with_browser_arg(
        self, mock_run, _mock_config, sessions_dir
    ):
        """install-browser --browser chrome passes the browser arg to subprocess."""
        mock_run.return_value = None
        main(["install-browser", "--browser", "chrome"])
        mock_run.assert_called_once_with(
            ["patchright", "install", "chrome"], check=True
        )

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("subprocess.run")
    def test_install_browser_without_browser_arg(
        self, mock_run, _mock_config, sessions_dir
    ):
        """install-browser without --browser runs patchright install with no extra args."""
        mock_run.return_value = None
        main(["install-browser"])
        mock_run.assert_called_once_with(["patchright", "install"], check=True)


class TestMainDaemonCommand:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.send_command")
    def test_daemon_command_success(
        self, mock_send, _mock_config, capsys, sessions_dir
    ):
        """A daemon command (goto) prints the output on success."""
        mock_send.return_value = {
            "ok": True,
            "output": "Navigated to https://example.com",
        }
        main(["goto", "https://example.com"])
        captured = capsys.readouterr()
        assert "Navigated to https://example.com" in captured.out
        mock_send.assert_called_once_with(
            "default", "goto", {"url": "https://example.com"}
        )

    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.send_command")
    def test_daemon_command_failure(
        self, mock_send, _mock_config, capsys, sessions_dir
    ):
        """A daemon command failure prints the error to stderr and exits 1."""
        mock_send.return_value = {"ok": False, "error": "Session not running"}
        with pytest.raises(SystemExit) as exc_info:
            main(["goto", "https://example.com"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Session not running" in captured.err


class TestMainGlobalFlags:
    @patch("patchright_cli.cli.load_config", return_value=CLIConfig())
    @patch("patchright_cli.cli.send_command")
    def test_session_flag(self, mock_send, _mock_config, sessions_dir):
        """-s session-name passes the session name to resolve_session_name."""
        mock_send.return_value = {"ok": True, "output": "done"}
        main(["-s", "my-session", "goto", "https://example.com"])
        # send_command should have been called with "my-session" as the session name
        mock_send.assert_called_once_with(
            "my-session", "goto", {"url": "https://example.com"}
        )

    @patch("patchright_cli.cli.send_command")
    @patch("patchright_cli.cli.load_config")
    def test_config_flag(self, mock_load_config, mock_send, sessions_dir):
        """--config path passes the path to load_config."""
        mock_load_config.return_value = CLIConfig()
        mock_send.return_value = {"ok": True, "output": "done"}
        main(["--config", "/tmp/my-config.json", "goto", "https://example.com"])
        mock_load_config.assert_called_once_with("/tmp/my-config.json")
