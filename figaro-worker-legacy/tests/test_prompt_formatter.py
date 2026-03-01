"""Tests for prompt formatter."""

from figaro_worker.worker.prompt_formatter import format_task_prompt


def test_format_task_prompt_basic():
    """Test basic prompt formatting without URL."""
    user_prompt = "Click the login button"
    formatted = format_task_prompt(user_prompt)

    assert "<task>" in formatted
    assert user_prompt in formatted
    assert "</task>" in formatted
    assert "<instructions>" in formatted
    assert "AskUserQuestion" in formatted
    assert "clarifying questions" in formatted.lower()


def test_format_task_prompt_with_url():
    """Test prompt formatting with start URL."""
    user_prompt = "Click the login button"
    start_url = "https://example.com"
    formatted = format_task_prompt(user_prompt, start_url)

    assert "<task>" in formatted
    assert user_prompt in formatted
    assert "</task>" in formatted
    assert "<context>" in formatted
    assert "<starting_url>" in formatted
    assert start_url in formatted
    assert "</starting_url>" in formatted
    assert "<instructions>" in formatted


def test_format_task_prompt_no_url():
    """Test prompt formatting with None URL."""
    user_prompt = "Check the weather"
    formatted = format_task_prompt(user_prompt, None)

    # Should not include context section when no URL
    assert "<context>" not in formatted
    assert "<starting_url>" not in formatted
    assert "<task>" in formatted
    assert user_prompt in formatted


def test_format_task_prompt_instructions_present():
    """Test that critical instructions are present."""
    user_prompt = "Do something"
    formatted = format_task_prompt(user_prompt)

    # Check for key instruction elements
    assert "CRITICAL" in formatted
    assert "Before executing" in formatted
    assert "ANALYZE THE TASK" in formatted
    assert "IDENTIFY WHAT NEEDS CLARIFICATION" in formatted
    assert "ASK CLARIFYING QUESTIONS" in formatted
    assert "AskUserQuestion" in formatted
    assert "Target Items/Information" in formatted
    assert "Action Specifics" in formatted
    assert "EXECUTE ONLY AFTER CLARIFICATION" in formatted
