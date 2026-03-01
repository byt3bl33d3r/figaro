FROM mcr.microsoft.com/devcontainers/python:2-3.14-trixie

RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && rm -f /usr/share/keyrings/yarn.gpg

# RUN apt-get update && apt-get install --no-install-recommends -y \
#     chromium \
#     chromium-driver \
#     && rm -rf /var/lib/apt/lists/*

# # Force-install extension via policy
# RUN mkdir -p /etc/chromium/policies/managed
# RUN echo '{"ExtensionInstallForcelist":["fcoeoabgfenejglbffodgkkbkcdhcgfn;https://clients2.google.com/service/update2/crx"]}' \
#     > /etc/chromium/policies/managed/claude.json

USER vscode
ENV CLAUDE_CODE_SUBAGENT_MODEL="claude-opus-4-6"
RUN echo 'alias claude="claude --dangerously-skip-permissions"' >> ~/.bashrc
#ENV PLAYWRIGHT_MCP_EXECUTABLE_PATH=/usr/bin/chromium

# # Create profile directory structure
# RUN mkdir -p "/home/vscode/.config/chromium/Default/Local Extension Settings/fcoeoabgfenejglbffodgkkbkcdhcgfn"

# # Copy pre-authenticated extension storage
# COPY --chown=vscode:vscode [ \
#     "claude-chrome-auth/", \
#     "/home/vscode/.config/chromium/Default/Local Extension Settings/fcoeoabgfenejglbffodgkkbkcdhcgfn/" \
#     ]
