# Separate verifier image. It never shares a container with the agent; Harbor
# places the game log collected from the mcp-server sidecar at /snapshot/game.json.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /app
COPY . /tests/
RUN chmod +x /tests/test.sh
