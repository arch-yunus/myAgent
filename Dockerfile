FROM python:3.12-slim

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        git \
        curl \
        wget \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Node-based CLIs
# ---------------------------------------------------------------------------
RUN npm install -g @google/gemini-cli @anthropic-ai/claude-code \
    && npm cache clean --force

# ---------------------------------------------------------------------------
# Python tooling
# ---------------------------------------------------------------------------
RUN pip install --no-cache-dir uv

# ---------------------------------------------------------------------------
# myagent install — two-layer caching strategy:
#   Layer A: third-party deps  (cached until requirements.txt changes)
#   Layer B: package install   (re-runs only when source code changes)
# ---------------------------------------------------------------------------
WORKDIR /app

# Layer A: install third-party deps from requirements.txt + tooling
COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt \
    && uv pip install --system ruff pytest requests

# Layer B: copy source, then install the package itself (non-editable, no-deps)
COPY . .
RUN uv pip install --system --no-deps .

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------

# Work directory — mapped to host via volume
RUN mkdir -p /workspace
WORKDIR /workspace

# Tell executor to run in unrestricted mode (Docker IS the sandbox)
ENV MYAGENT_DOCKER=1
ENV MYAGENT_WORK_DIR=/workspace

# Run as root inside container — Docker is the security boundary.
# This ensures mounted host auth dirs (~/.gemini, ~/.claude) are accessible
# regardless of the host user's UID.
ENV HOME=/root

ENTRYPOINT ["myagent"]
