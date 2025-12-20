FROM python:3.11-slim

# Install dependencies for installing other tools
RUN apt-get update && apt-get install -y \
  curl \
  git \
  ipython3 \
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
RUN npm i -g @openai/codex @google/gemini-cli \
  && npm i -g @modelcontextprotocol/server-filesystem \
  && curl -fsSL https://claude.ai/install.sh | bash \
  && true

# claude install.sh typically drops binaries in ~/.local/bin
ENV PATH="/root/.local/bin:$PATH"

# Working directory
WORKDIR /app

# Install Node dependencies needed by the app (Codex SDK)
COPY package.json .
RUN npm install --omit=dev

# Copy python dependencies
COPY requirements.txt .

# Install python dependencies using uv
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application
COPY . .

# Bundle Supabase JS locally so Spaces can run without external CDNs.
RUN node - <<'NODE'
const fs = require('fs');
const path = require('path');

function walk(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const base = path.join(process.cwd(), 'node_modules', '@supabase', 'supabase-js');
if (!fs.existsSync(base)) {
  console.log('[build] @supabase/supabase-js not installed; skipping bundle copy');
  process.exit(0);
}

const dist = path.join(base, 'dist');
const files = fs.existsSync(dist) ? walk(dist) : walk(base);
const candidates = files.filter((f) => /supabase(\.min)?\.js$/i.test(f)).sort();
if (!candidates.length) {
  console.log('[build] No supabase JS bundle found in package; skipping');
  process.exit(0);
}

const src =
  candidates.find((f) => /umd[\\/].*supabase\.min\.js$/i.test(f)) ||
  candidates.find((f) => /umd[\\/].*supabase\.js$/i.test(f)) ||
  candidates.find((f) => /supabase\.min\.js$/i.test(f)) ||
  candidates[0];

const dst = path.join(process.cwd(), 'static', 'vendor', 'supabase-js.min.js');
fs.mkdirSync(path.dirname(dst), { recursive: true });
fs.copyFileSync(src, dst);
console.log(`[build] Copied ${src} -> ${dst}`);
NODE

# Expose port 7860 for HF Spaces
EXPOSE 7860

# Codex auth: tokens should come from HF Spaces Secrets at runtime.
# Leave CODEX_ACCOUNT_ID empty by default; set it as a Secret if your tokens require it.
ENV CODEX_ACCOUNT_ID=""

# Generate SSH keys at runtime (for git over SSH), then start app
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
