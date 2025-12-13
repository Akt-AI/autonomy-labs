FROM python:3.11-slim

# Install dependencies for installing other tools
RUN apt-get update && apt-get install -y \
    curl \
    git \
    openssh-client \
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
RUN printf '%s\n' \
    'export PROMPT_HOST_SHORT="${PROMPT_HOST_SHORT:-$(hostname | cut -c1-8)}"' \
    'export PS1="\\u@${PROMPT_HOST_SHORT}:\\w\\$ "' \
    '' \
    '# Codex auth: device flow works best in container/web terminals.' \
    "alias codex-login='codex login --device-auth'" \
    "printf '\\n[codex] Tip: in Spaces/web terminals use device auth: codex login --device-auth (or codex-login)\\n\\n'" \
  >> /root/.bashrc

# Install CLI tools (network required at build time)
RUN npm i -g @openai/codex \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        '' \
        '# Using npx (no installation required)' \
        'exec npx https://github.com/google-gemini/gemini-cli \"$@\"' \
      > /usr/local/bin/gemini-cli \
    && chmod +x /usr/local/bin/gemini-cli

# claude install.sh typically drops binaries in ~/.local/bin
ENV PATH="/root/.local/bin:$PATH"

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

# Generate SSH keys at runtime (for git over SSH), then start app
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
