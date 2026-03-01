# Security Considerations

This document catalogues known security concerns in the Figaro system that are currently accepted or disregarded. Figaro is designed as an internal orchestration tool running in trusted environments (local dev, private networks). These trade-offs prioritize user experience. If you want to run this in "production" it is essential you use encrypted overlay networks like Tailscale, Headscale, or Nebula.

**This is not a TODO list** — these are conscious trade-offs. If Figaro is ever exposed to untrusted networks or users, every item here becomes a real vulnerability.

---

### 1. NATS has no authentication or TLS

**Files:** `nats.conf`, all service configs

The NATS server runs with zero authentication and explicit `no_tls: true` on the WebSocket port. In the base compose, NATS does not publish any ports and is only reachable on the internal `figaro-net` Docker network. However, both the dev overlay (127.0.0.1:8443) and prod overlay (0.0.0.0:8443) expose the WebSocket port to the host. Any client that can reach the exposed port has full access to:

- Subscribe to all subjects (task data, VNC passwords, credentials, conversation history)
- Publish to any subject (create tasks, impersonate workers/supervisors, send fake completions)
- Access JetStream (read entire task history)

All inter-service NATS traffic uses `nats://` (plaintext) over the Docker bridge network. The NATS monitoring endpoint on port 8222 is also unauthenticated but is not published to the host in any compose file.

### 2. NATS WebSocket bound to all interfaces in production

**File:** `docker-compose.prod.yml:3-4`

```yaml
nats:
  ports:
    - "0.0.0.0:8443:8443"
```

The unauthenticated NATS WebSocket is exposed on all network interfaces in the production compose file. Combined with the lack of auth, anyone on the network can connect and take full control of the system. the prod-local overlay and the dev compose correctly binds to `127.0.0.1`.

### 3. Workers run Claude agents with `bypassPermissions` by default

**File:** `figaro-worker/src/worker/executor.ts:136-142`

```typescript
const permissionMode = (optionsDict.permission_mode as PermissionMode | undefined) ?? "bypassPermissions";
```

All tasks default to `bypassPermissions` mode, allowing the Claude agent to execute any tool (shell commands, file writes, etc.) without human approval. Since there's no auth on NATS, anyone who can reach the NATS server can submit a task that executes arbitrary commands on worker desktops.

---

### 4. Claude credentials bind-mounted from host into containers

**File:** `docker-compose.yml:68-69, 89-90`

```yaml
volumes:
  - ~/.claude.json:/home/vscode/.claude.json
  - ~/.claude/.credentials.json:/home/vscode/.claude/.credentials.json
```

Host Claude authentication tokens are mounted directly into worker and supervisor containers. If a container is compromised (e.g., via a malicious task prompt exploiting `bypassPermissions`), the attacker gains the host user's Claude credentials.

### 5. VNC passwords broadcast in plaintext over NATS

**File:** `figaro/src/figaro/services/nats_service.py:741, 969`

VNC passwords are included in worker broadcast messages (`figaro.broadcast.workers`) and API responses (`figaro.api.workers`). NATS traffic travels unencrypted over the `figaro-net` Docker network. In the base compose, NATS is not exposed to the host, but any container on the bridge network (or any client reaching an exposed overlay port) can subscribe and receive all worker VNC passwords in cleartext.

```python
"vnc_password": w.vnc_password,
```

### 6. Supervisor agent receives VNC credentials explicitly

**Files:** `figaro-supervisor/src/figaro_supervisor/supervisor/tools.py:233`, `processor.py:70,113`

The `list_workers` tool returns `vnc_username` and `vnc_password` to the AI supervisor agent. The system prompt instructs the supervisor to use these credentials to unlock lock screens. This means VNC passwords flow through:

1. Worker registration -> NATS (plaintext) -> Orchestrator -> NATS (plaintext) -> Supervisor
2. Into the Claude API as tool results (sent to Anthropic's servers as part of the conversation)

### 7. Containerized workers have VNC servers that listen on all interfaces without authentication

**File:** `container-desktop-install.sh:389,394`

```bash
common_options="tigervncserver ... -localhost 0 ..."
# When no VNC_PASSWORD is set:
-SecurityTypes None --I-KNOW-THIS-IS-INSECURE
```

The `-localhost 0` flag binds VNC to all interfaces inside the container. Without a VNC password, the server explicitly disables all security. However, worker containers do not publish any ports to the host — VNC is only reachable from other containers on the `figaro-net` Docker bridge network (i.e., the orchestrator, supervisor, and other internal services). Direct access from outside the Docker network is not possible unless ports are explicitly mapped in a compose overlay.

### 8. VNC passwords stored unencrypted in database

**File:** `figaro/src/figaro/db/models.py:259`

```python
vnc_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

VNC passwords are stored as plaintext in the PostgreSQL `desktop_workers` table. No encryption at rest. PostgreSQL does not publish any ports to the host in any compose file — it is only reachable from other containers on the `figaro-net` Docker network.

### 9. No authentication on HTTP/WebSocket endpoints

**Files:** `figaro/src/figaro/app.py`, `routes/websocket.py`, `routes/config.py`

The FastAPI application has:

- No authentication middleware on any endpoint
- The VNC proxy WebSocket (`/vnc/{worker_id}`) accepts any connection without auth
- The config endpoint exposes the NATS WebSocket URL to any requester
- No rate limiting

In the base compose, the orchestrator does not publish any ports and is only reachable on the `figaro-net` Docker network. The dev overlay exposes it on 127.0.0.1:8000 and the prod overlay on 0.0.0.0:8000.

### 10. Hardcoded database credentials

**Files:** `docker-compose.yml:5-7`, `figaro/src/figaro/config.py:15`

```yaml
POSTGRES_USER: figaro
POSTGRES_PASSWORD: figaro
```

Database credentials are hardcoded as `figaro/figaro` in both compose files and the application's default config. PostgreSQL does not publish any ports in any compose file — it is only reachable on the internal `figaro-net` Docker network.

---

### 11. No CORS configuration

**File:** `figaro/src/figaro/app.py`

The FastAPI app has no CORS middleware. Any website can make requests to the orchestrator API and establish WebSocket connections to the VNC proxy, enabling cross-origin attacks from a user's browser.

### 12. Docker containers use `ipc: host`

**Files:** `docker-compose.yml:72`, `docker-compose.dev.yml:22`

Workers run with `ipc: host`, sharing the host's IPC namespace. Required for Chromium's shared memory but widens the container escape surface.

### 13. VNC proxy enables SSRF

**Files:** `figaro/src/figaro/vnc_proxy.py`, `services/nats_service.py:1299-1374`

The VNC proxy connects to whatever `novnc_url` is registered by a worker. Since NATS registration is unauthenticated, an attacker with access to NATS can register a fake worker pointing `novnc_url` at internal services on the `figaro-net` Docker network, using the orchestrator as an SSRF proxy into the private network.

### 14. All VNC traffic unencrypted

**Files:** `figaro/src/figaro/services/vnc_client.py`, `vnc_proxy.py`

All asyncvnc connections use plain TCP or `ws://` (not `wss://`). VNC traffic — including screenshots of potentially sensitive content and keyboard input (passwords typed by the supervisor) — travels unencrypted over the `figaro-net` Docker network. Worker VNC ports are not published to the host; the orchestrator connects to them internally and proxies to external clients.

### 15. Default VNC password is well-known

**Files:** `container-desktop-install.sh:11`, `figaro-ui/.env.example:8`

```bash
VNC_PASSWORD=${PASSWORD:-"vscode"}
```

The default VNC password `vscode` is the standard VS Code devcontainer password. The UI also bakes this default into the frontend bundle via `VITE_VNC_DEFAULT_PASSWORD`.

### 16. Wildcard injection in task search

**File:** `figaro/src/figaro/db/repositories/tasks.py:336`

```python
.where(TaskModel.prompt.ilike(f"%{query}%"))
```

While SQLAlchemy parameterizes the value (no SQL injection), user input containing `%` or `_` can perform wildcard-based data discovery across task prompts.

### 17. No Content Security Policy headers

No CSP headers are configured anywhere. The UI SPA has no browser-level protection against XSS via content injection.

---

### 18. Remote scripts piped to bash during build

**Files:** `Dockerfile.worker-desktop:39`, `figaro-supervisor/Dockerfile:31`, `.devcontainer/devcontainer.json:45`

```dockerfile
RUN curl -fsSL https://claude.ai/install.sh | bash
```

The Claude CLI (and bun, uv) are installed by piping remote scripts directly to bash. A compromise of these URLs would inject malicious code into all builds.

### 19. Custom seccomp profile allows ptrace

**File:** `seccomp_profile.json:409-419`

All containerized workers run under a custom seccomp profile (`seccomp_profile.json`) that restricts syscalls to only those required by Chromium. The profile allows the `ptrace` syscall, required for Chromium debugging, which expands the container attack surface.

### 20. VNC password baked into UI frontend bundle

**File:** `figaro-ui/src/hooks/useNoVNC.ts:71`

```typescript
password = import.meta.env.VITE_VNC_DEFAULT_PASSWORD || '',
```

The VNC password is readable in the served JavaScript bundle by anyone who loads the UI.

### 21. Orchestrator binds to 0.0.0.0

**Files:** `figaro/src/figaro/config.py:5`, `docker-compose.prod.yml:8`

The orchestrator HTTP server defaults to binding on `0.0.0.0` inside its container, but the base `docker-compose.yml` does not publish any orchestrator ports — it is only reachable on the internal `figaro-net` Docker network. The dev overlay exposes it on `127.0.0.1`, while the prod overlay exposes it on `0.0.0.0` on the host, making the config endpoint and VNC proxy accessible on all host interfaces.

### 22. JavaScript eval capability in browser automation

**File:** `patchright-cli/src/patchright_cli/server.py:851`

The `cmd_eval` function allows evaluating arbitrary JavaScript in the browser page. By design for automation, but combined with `bypassPermissions`, any task prompt has full JS execution in the browser context.

---

## Summary of Attack Vectors

| Vector | Prerequisites | Impact |
|--------|--------------|--------|
| Full system takeover via NATS | Access to exposed NATS overlay port (dev: 127.0.0.1:8443, prod: 0.0.0.0:8443) or the Docker network | Create tasks, steal credentials, impersonate any component |
| Arbitrary code execution on workers | Access to NATS | Submit task with `bypassPermissions`, execute shell commands |
| VNC desktop hijacking | Container on `figaro-net` (VNC ports are not published to host) | View/control worker desktops, observe sensitive data |
| Credential theft via container escape | Malicious task prompt | Steal host Claude credentials from bind-mounted volumes |
| SSRF via fake worker registration | Access to NATS | Use orchestrator to probe `figaro-net` internal services |

---

## Why This Is Acceptable (For Now)

Figaro is designed to run in trusted, isolated environments:

- **Local development**: All services on localhost behind NAT/firewall
- **Private Docker networks**: Inter-service communication stays on `figaro-net`
- **Overlay networks**: For remote access, Figaro is designed to run on encrypted overlay networks like Tailscale, Headscale, or Nebula — where all traffic is encrypted in transit and access is restricted to authenticated peers. This avoids exposing services to the public internet while enabling remote operation without additional TLS/auth configuration
- **Controlled access**: Only the operator submits tasks and views the UI

If the deployment model changes (multi-tenant, public internet, untrusted users), these issues must be addressed before exposure.
