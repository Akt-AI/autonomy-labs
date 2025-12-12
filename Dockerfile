FROM python:3.11-slim

# Install dependencies for installing other tools
RUN apt-get update && apt-get install -y \
    curl \
    git \
    vim \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install uv (specific version 0.9.17)
RUN curl -LsSf https://astral.sh/uv/0.9.17/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install nvm and Node.js v24
ENV NVM_DIR="/root/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install 24 \
    && nvm alias default 24 \
    && nvm use default

# Add Node and npm to PATH
ENV PATH="$NVM_DIR/versions/node/v24.12.0/bin:$PATH"

# Enable pnpm
RUN corepack enable pnpm

# Shorten terminal hostname/prompt for interactive shells
ENV HOSTNAME=sandbox
RUN echo 'export PS1="\\u@sandbox:\\w\\$ "' >> /root/.bashrc

# Install real CLI tools (network required at build time)
RUN npm install -g @google/generative-ai-cli @anthropic-ai/claude-code \
    && printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        '' \
        '# Wrapper for Google Gemini/GenAI CLI (package name may change over time).' \
        'for candidate in genai generative-ai gemini; do' \
        '  if command -v \"$candidate\" >/dev/null 2>&1; then' \
        '    exec \"$candidate\" \"$@\"' \
        '  fi' \
        'done' \
        'echo \"Gemini CLI not found on PATH; package install may have changed.\" >&2' \
        'exit 127' \
      > /usr/local/bin/gemini-cli \
    && chmod +x /usr/local/bin/gemini-cli \
    && printf '%s\n' \
        '#!/usr/bin/env bash' \
        'echo \"codex: no official OpenAI CLI is installed in this image.\"' \
        'echo \"Use the Codex CLI app or an OpenAI SDK instead.\"' \
      > /usr/local/bin/codex \
    && chmod +x /usr/local/bin/codex

# Working directory
WORKDIR /app

# Copy python dependencies
COPY requirements.txt .

# Install python dependencies using uv
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application
COPY . .

# Expose port 7860 for HF Spaces
EXPOSE 7860

# Command to run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
