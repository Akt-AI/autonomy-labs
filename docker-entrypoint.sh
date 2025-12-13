#!/usr/bin/env bash
set -euo pipefail

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
  ensure_ssh_keypair
else
  echo "[git ssh] ssh-keygen not found; install openssh-client to enable SSH key generation." >&2
fi

exec "$@"

