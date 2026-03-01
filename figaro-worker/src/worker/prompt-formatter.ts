export function formatTaskPrompt(
  userPrompt: string,
  startUrl?: string,
): string {
  let navigationContext = "";
  if (startUrl) {
    navigationContext = `
<context>
<starting_url>${startUrl}</starting_url>
</context>

`;
  }

  const formattedPrompt = `${navigationContext}<task>
${userPrompt}
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

## Browser Automation

- When the task involves navigating to a specific website and searching for or extracting information, prefer using \`patchright-cli\` for browser automation if the skill is available. Key commands: \`patchright-cli open <url>\`, \`patchright-cli snapshot\`, \`patchright-cli click\`, \`patchright-cli fill\`, \`patchright-cli type\`, \`patchright-cli press\`.
- If the browser already displays results from a previous task or session (stale page), reload the page or redo the search to ensure fresh, up-to-date results.

</instructions>`;

  return formattedPrompt;
}
