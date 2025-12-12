FROM python:3.11-slim

# Install dependencies for installing other tools
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    vim \
    chromium \
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

# Lightweight CLI shims for AI tools so they are always available in the container
# Users can replace the placeholders with real implementations or wrap SDKs as needed.
RUN set -eux; \
    cat <<'EOF' >/usr/local/bin/codex && chmod +x /usr/local/bin/codex
#!/usr/bin/env bash
echo "codex CLI placeholder. Provide OPENAI_API_KEY and dispatch prompts here."
EOF
RUN set -eux; \
    cat <<'EOF' >/usr/local/bin/gemini-cli && chmod +x /usr/local/bin/gemini-cli
#!/usr/bin/env bash
echo "gemini-cli placeholder. Set GEMINI_API_KEY and call https://generativelanguage.googleapis.com APIs."
EOF
RUN set -eux; \
    cat <<'EOF' >/usr/local/bin/claude-cli && chmod +x /usr/local/bin/claude-cli
#!/usr/bin/env bash
echo "claude-cli placeholder. Configure ANTHROPIC_API_KEY to proxy requests."
EOF

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
