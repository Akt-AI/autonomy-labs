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

persist_ssh_dir_if_possible() {
  local persistent_root="/data"
  local ssh_home="${HOME}/.ssh"
  local persistent_ssh="${persistent_root}/.ssh"

  if [[ ! -d "${persistent_root}" ]] || [[ ! -w "${persistent_root}" ]]; then
    return 0
  fi

  mkdir -p "${persistent_ssh}"
  chmod 700 "${persistent_ssh}" || true

  if [[ -L "${ssh_home}" ]]; then
    return 0
  fi

  if [[ -d "${ssh_home}" ]] && [[ -n "$(ls -A "${ssh_home}" 2>/dev/null || true)" ]]; then
    mkdir -p "${persistent_ssh}"
    cp -a "${ssh_home}/." "${persistent_ssh}/" 2>/dev/null || true
    rm -rf "${ssh_home}"
  else
    rm -rf "${ssh_home}" 2>/dev/null || true
  fi

  ln -s "${persistent_ssh}" "${ssh_home}"
  echo "[ssh] Using persistent config dir: ${ssh_home} -> ${persistent_ssh}"
}

ensure_codex_workspace_dir() {
  local persistent_root="/data"
  local workspace_dir="${persistent_root}/codex/workspace"
  if [[ ! -d "${persistent_root}" ]] || [[ ! -w "${persistent_root}" ]]; then
    return 0
  fi
  mkdir -p "${workspace_dir}"
  chmod 700 "${persistent_root}/codex" 2>/dev/null || true
  chmod 700 "${workspace_dir}" 2>/dev/null || true
  chown -R "$(id -u)":"$(id -g)" "${persistent_root}/codex" 2>/dev/null || true
  echo "[codex] Default workspace: ${workspace_dir}"
}

ensure_codex_home_permissions() {
  local codex_home="${HOME}/.codex"
  mkdir -p "${codex_home}/sessions" "${codex_home}/logs" 2>/dev/null || true
  chmod 700 "${codex_home}" 2>/dev/null || true
  # Ensure the current user can write (handles cases where files were created as another user).
  chown -R "$(id -u)":"$(id -g)" "${codex_home}" 2>/dev/null || true
}

ensure_codex_auth_from_env() {
  local codex_home="${HOME}/.codex"
  local auth_path="${codex_home}/auth.json"
  local dot_auth_path="${codex_home}/.auth.json"

  # Tokens should be provided as HF Spaces secrets / env vars at runtime.
  # - CODEX_ID_TOKEN
  # - CODEX_ACCESS_TOKEN
  # - CODEX_REFRESH_TOKEN
  # Optional:
  # - CODEX_ACCOUNT_ID (defaults to image ENV)
  if [[ -z "${CODEX_ID_TOKEN:-}" ]] && [[ -z "${CODEX_ACCESS_TOKEN:-}" ]] && [[ -z "${CODEX_REFRESH_TOKEN:-}" ]]; then
    return 0
  fi

  mkdir -p "${codex_home}"
  local auth_json
  auth_json="$(cat <<EOF
{
  "OPENAI_API_KEY": null,
  "tokens": {
    "id_token": "${CODEX_ID_TOKEN:-}",
    "access_token": "${CODEX_ACCESS_TOKEN:-}",
    "refresh_token": "${CODEX_REFRESH_TOKEN:-}",
    "account_id": "${CODEX_ACCOUNT_ID:-}"
  },
  "last_refresh": null
}
EOF
)"

  printf '%s\n' "${auth_json}" >"${auth_path}"
  printf '%s\n' "${auth_json}" >"${dot_auth_path}"

  chmod 600 "${auth_path}" "${dot_auth_path}" 2>/dev/null || true
  chown "$(id -u)":"$(id -g)" "${auth_path}" "${dot_auth_path}" 2>/dev/null || true
  echo "[codex] Wrote auth config from env to: ${auth_path} and ${dot_auth_path}"
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

persist_codex_dir_if_possible
ensure_codex_home_permissions
ensure_codex_auth_from_env
persist_ssh_dir_if_possible
ensure_codex_workspace_dir

if command -v ssh-keygen >/dev/null 2>&1; then
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

ensure_codex_mcp_server() {
  if ! command -v codex >/dev/null 2>&1; then
    return 0
  fi
  if codex mcp list 2>/dev/null | awk '{print $1}' | grep -qx "codex"; then
    return 0
  fi
  # Expose Codex itself as an MCP server (stdio). Name: codex
  codex mcp add codex -- codex mcp-server >/dev/null 2>&1 || true
}

ensure_codex_mcp_server

exec "$@"
