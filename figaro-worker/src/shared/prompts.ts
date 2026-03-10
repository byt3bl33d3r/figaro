/** Shared prompt instruction blocks used by both worker and supervisor. */

export const TASK_QUERY_INSTRUCTIONS = `- To list, search, or look up previous tasks, you MUST use the \`python_exec\` tool with the \`figaro\` module
- \`figaro.list_tasks()\` — list all recent tasks (returns up to 50 by default)
- \`figaro.list_tasks(status='completed', limit=20)\` — filter by status, limit, or worker_id
- \`figaro.search_tasks('query')\` — search tasks by keyword in prompts, results, and messages
- \`figaro.search_tasks('query', status='completed', limit=10)\` — search with filters
- \`figaro.get_task('task-id')\` — get full task details with message history
- Do NOT try to answer task queries from memory — always use python_exec to fetch live data`;

export const MEMORY_INSTRUCTIONS = `- Use the \`python_exec\` tool with the \`figaro\` module to save and recall persistent memories
- \`figaro.save_memory('content', metadata={'key': 'value'}, collection='default')\` — save a memory for future recall. Memories are deduplicated by content hash within a collection.
- \`figaro.search_memories('query', limit=10, collection=None)\` — search memories using hybrid BM25 + vector search. Returns results ranked by relevance.
- \`figaro.list_memories(collection=None, limit=50)\` — list all memories, optionally filtered by collection
- \`figaro.delete_memory('memory-id')\` — delete a memory by ID
- Use memories to store important information learned during tasks: user preferences, site credentials hints, navigation patterns, recurring issues, and solutions`;
