"""API tests for scheduled task endpoints.

Scheduled task REST endpoints (GET/POST/PUT/DELETE /api/scheduled-tasks) have been
removed. Scheduled task operations are now handled via NATS request/reply in NatsService.
"""
