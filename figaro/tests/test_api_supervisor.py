"""API tests for supervisor endpoints.

Supervisor REST endpoints (GET /api/supervisor/status, POST /api/supervisor/delegate)
have been removed. Supervisor operations are now handled via NATS request/reply
in NatsService.
"""
