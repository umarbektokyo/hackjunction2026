# Agent container ("main"). Contains no game code: only Python, an MCP client
# library and the Codex CLI, so the game is reachable exclusively through
# http://mcp-server:8000/mcp.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils curl git procps ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-client.txt /tmp/requirements-client.txt
RUN pip install --no-cache-dir -r /tmp/requirements-client.txt && rm /tmp/requirements-client.txt

# Codex CLI, installed the same way Harbor's codex agent installs it (nvm + npm -g),
# so `harbor run -a codex` finds it and skips its per-trial install.
ARG NVM_VERSION=v0.40.2
ARG NODE_MAJOR=22
ARG CODEX_VERSION=0.167.1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL -o- "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | bash \
    && export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" \
    && nvm install "${NODE_MAJOR}" && nvm alias default "${NODE_MAJOR}" \
    && npm i -g "@openai/codex@${CODEX_VERSION}" \
    && codex --version \
    && nvm cache clear && npm cache clean --force \
    && ln -s "$(dirname "$(nvm which default)")"/{node,npm,npx,codex} /usr/local/bin/

WORKDIR /app
