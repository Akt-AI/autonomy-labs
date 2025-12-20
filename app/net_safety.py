from __future__ import annotations

import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def is_public_host(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception:
        return False

    import ipaddress

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def validate_public_http_url(
    url: str,
    *,
    allowed_hosts: set[str] | None = None,
) -> str:
    u = (url or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Missing URL"})
    p = urlparse(u)
    if p.scheme not in {"https", "http"}:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "URL must be http(s)"})
    if not p.netloc:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "URL must include a host"})
    host = (p.hostname or "").strip().lower()
    if allowed_hosts is not None and host not in allowed_hosts:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Host is not allowed"})
    if not is_public_host(host):
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Host is not allowed"})
    return p._replace(fragment="").geturl()

