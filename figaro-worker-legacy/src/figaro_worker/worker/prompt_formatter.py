"""Prompt formatter for Claude Agent SDK following best practices."""


def format_task_prompt(user_prompt: str, start_url: str | None = None) -> str:
    """Format a user task prompt with XML structure and clarification requirements.

    Args:
        user_prompt: The raw task description from the user
        start_url: Optional starting URL for navigation tasks

    Returns:
        A properly formatted prompt following Claude best practices
    """
    # Build the navigation context if URL is provided
    navigation_context = ""
    if start_url:
        navigation_context = f"""
<context>
<starting_url>{start_url}</starting_url>
</context>

"""

    formatted_prompt = f"""{navigation_context}<task>
{user_prompt}
</task>

<instructions>
CRITICAL: Before executing this task, you MUST carefully analyze it and ask clarifying questions with the AskUserQuestion tool.

Step 1: ANALYZE THE TASK
Read the task description and identify:
- What is the main objective?
- What specific information or actions are required?
- What assumptions would I need to make?
- What could go wrong or be ambiguous?

Step 2: IDENTIFY WHAT NEEDS CLARIFICATION
Check if ANY of the following are unclear or missing:

**Target Items/Information:**
- What exactly am I looking for? (product names, specific data, links, etc.)
- Are there specific criteria or filters?
- What variations or alternatives are acceptable?

**Action Specifics:**
- Are there any specific steps to follow in a particular order?
- Should I verify or double-check anything?

Step 3: ASK CLARIFYING QUESTIONS
If you identified ANY unclear aspects, you MUST use the AskUserQuestion tool to ask for clarification BEFORE proceeding with execution.

Be specific in your questions

Step 4: EXECUTE ONLY AFTER CLARIFICATION
Only proceed with task execution AFTER you have all the information needed to complete it successfully without making assumptions.

</instructions>"""

    return formatted_prompt
