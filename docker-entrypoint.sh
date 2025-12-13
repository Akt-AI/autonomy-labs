#!/usr/bin/env bash
set -euo pipefail

persist_codex_dir_if_possible() {
  local persistent_root="/data"
  local codex_home="${HOME}/.codex"
  local persistent_codex="${persistent_root}/.codex"

  if [[ ! -d "${persistent_root}" ]] || [[ ! -w "${persistent_root}" ]]; then
    return 0
  fi

  mkdir -p "${persistent_codex}"
  chmod 700 "${persistent_codex}" || true

  if [[ -L "${codex_home}" ]]; then
    return 0
  fi

  if [[ -d "${codex_home}" ]] && [[ -n "$(ls -A "${codex_home}" 2>/dev/null || true)" ]]; then
    mkdir -p "${persistent_codex}"
    cp -a "${codex_home}/." "${persistent_codex}/" 2>/dev/null || true
    rm -rf "${codex_home}"
  else
    rm -rf "${codex_home}" 2>/dev/null || true
  fi

  ln -s "${persistent_codex}" "${codex_home}"
  echo "[codex] Using persistent config dir: ${codex_home} -> ${persistent_codex}"
}

ensure_ssh_keypair() {
  local ssh_dir="${HOME}/.ssh"
  local key_path="${ssh_dir}/id_ed25519"

  mkdir -p "${ssh_dir}"
  chmod 700 "${ssh_dir}"

  if [[ ! -f "${key_path}" ]]; then
    ssh-keygen -t ed25519 -N "" -f "${key_path}" -C "${SSH_KEY_COMMENT:-autonomy-labs}" >/dev/null
    chmod 600 "${key_path}"
    chmod 644 "${key_path}.pub"
    cat >"${ssh_dir}/config" <<'EOF'
Host *
  AddKeysToAgent no
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
    chmod 600 "${ssh_dir}/config"

    echo ""
    echo "[git ssh] Generated a new SSH keypair for this container:"
    echo "----------8<----------"
    cat "${key_path}.pub"
    echo "----------8<----------"
    echo "[git ssh] Add the public key above to your Git provider (GitHub/GitLab) to enable SSH auth."
    echo ""
  fi
}

if command -v ssh-keygen >/dev/null 2>&1; then
  persist_codex_dir_if_possible
  ensure_ssh_keypair
else
  echo "[git ssh] ssh-keygen not found; install openssh-client to enable SSH key generation." >&2
fi

ensure_filesystem_mcp() {
  if ! command -v codex >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v mcp-server-filesystem >/dev/null 2>&1; then
    return 0
  fi

  if codex mcp list 2>/dev/null | awk '{print $1}' | grep -qx "filesystem"; then
    return 0
  fi

  # Allow Codex to read (and if sandbox allows, write) within /app via filesystem MCP.
  codex mcp add filesystem -- mcp-server-filesystem /app >/dev/null 2>&1 || true
}

ensure_filesystem_mcp

exec "$@"
