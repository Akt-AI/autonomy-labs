FROM python:3.11-slim

# Set short hostname for terminal prompt
ENV HOSTNAME=sandbox

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

# Install AI CLI tools via npm
RUN npm install -g @anthropic-ai/claude-code @google/generative-ai || true

# Wrapper scripts for CLI tools (gemini-cli, claude-code already installed via npm)
# codex placeholder since OpenAI doesn't have official CLI
RUN set -eux; \
    cat <<'EOF' >/usr/local/bin/codex && chmod +x /usr/local/bin/codex
#!/usr/bin/env bash
echo "codex CLI - OpenAI doesn't provide official CLI. Use 'npx openai' or the API directly."
echo "Set OPENAI_API_KEY env var to authenticate."
EOF

# Alias gemini-cli to the installed package if available
RUN set -eux; \
    cat <<'EOF' >/usr/local/bin/gemini-cli && chmod +x /usr/local/bin/gemini-cli
#!/usr/bin/env bash
if command -v gemini &> /dev/null; then
    exec gemini "$@"
else
    echo "gemini-cli: Set GEMINI_API_KEY and use @google/generative-ai package"
    echo "Usage: export GEMINI_API_KEY=your_key"
fi
EOF

# Configure short PS1 prompt for terminal
RUN echo 'export PS1="\[\033[01;32m\]sandbox\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]# "' >> /root/.bashrc \
    && echo 'export HOSTNAME=sandbox' >> /root/.bashrc

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
