"""API tests for worker endpoints.

Worker REST endpoints (GET /api/workers, GET /api/workers/{id}/tasks) have been removed.
Worker operations are now handled via NATS request/reply in NatsService.
"""
