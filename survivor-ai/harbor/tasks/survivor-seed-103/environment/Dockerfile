# Agent container ("main"). Contains no game code: only Python, an MCP client
# library and the OpenCode CLI, so the game is reachable exclusively through
# http://mcp-server:8000/mcp.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils curl git procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-client.txt /tmp/requirements-client.txt
RUN pip install --no-cache-dir -r /tmp/requirements-client.txt && rm /tmp/requirements-client.txt

# OpenCode, installed the same way Harbor's opencode agent installs it (nvm + npm -g),
# so `harbor run -a opencode` finds it and skips its ~3 minute per-trial install.
# Remove this block and Harbor installs the latest OpenCode itself at trial start.
ARG NVM_VERSION=v0.40.2
ARG NODE_MAJOR=22
ARG OPENCODE_VERSION=1.19.5
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL -o- "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | bash \
    && export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" \
    && nvm install "${NODE_MAJOR}" && nvm alias default "${NODE_MAJOR}" \
    && npm i -g "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version \
    && nvm cache clear && npm cache clean --force \
    && ln -s "$(dirname "$(nvm which default)")"/{node,npm,npx} /usr/local/bin/
# node/npm on PATH (and procps above) also let Harbor's other agent installers,
# e.g. `-a claude-code`, skip their apt-get step.

# Claude Code, pre-installed the way Harbor's claude-code agent installs it (bootstrap.sh into
# ~/.local/bin), so `harbor run -a claude-code` skips its per-trial download. Without this,
# 15+ parallel trials hit Harbor's 360 s agent-setup timeout.
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://downloads.claude.ai/claude-code-releases/bootstrap.sh | bash -s -- \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude \
    && claude --version
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app
