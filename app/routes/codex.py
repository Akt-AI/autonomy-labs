from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.settings import feature_enabled
from app.workdir import safe_user_workdir

router = APIRouter()


class CodexRequest(BaseModel):
    message: str
    threadId: str | None = None
    model: str | None = None
    sandboxMode: str | None = "workspace-write"
    approvalPolicy: str | None = "never"
    apiKey: str | None = None
    baseUrl: str | None = None
    modelReasoningEffort: str | None = "minimal"
    workingDirectory: str | None = None


@router.post("/api/codex")
async def codex_agent(request: CodexRequest, http_request: Request):
    """
    Backwards-compatible alias for Codex CLI execution.

    Historically this endpoint used the Node SDK wrapper, but CLI-first keeps auth consistent with
    device-auth sessions and reduces SDK/CLI mismatch risk.
    """
    return await codex_agent_cli(request, http_request)


def _with_codex_agent_prefix(message: str) -> str:
    msg = message.strip()
    if msg.startswith("@"):
        return message
    return f"@codex {message}"


@router.post("/api/codex/cli")
async def codex_agent_cli(request: CodexRequest, http_request: Request):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Message is required"})
    if not feature_enabled("codex"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Codex is disabled"})

    user = await require_user_from_request(http_request)
    message = _with_codex_agent_prefix(request.message)

    base_args = ["codex", "exec", "--json", "--color", "never", "--sandbox", request.sandboxMode or "workspace-write"]
    if request.approvalPolicy:
        base_args += ["--config", f'approval_policy="{request.approvalPolicy}"']
    if request.model:
        base_args += ["--model", request.model]
    base_args += ["--cd", safe_user_workdir(user, request.workingDirectory), "--skip-git-repo-check"]

    if request.threadId:
        base_args += ["resume", request.threadId, message]
    else:
        base_args += [message]

    env = os.environ.copy()
    if request.apiKey:
        env["OPENAI_API_KEY"] = request.apiKey
        env["CODEX_API_KEY"] = request.apiKey
        if request.baseUrl:
            env["OPENAI_BASE_URL"] = request.baseUrl

    try:
        proc = await asyncio.create_subprocess_exec(
            *base_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()

        err_text = (stderr.decode("utf-8", errors="ignore") or "").strip()
        if proc.returncode != 0:
            out_text = (stdout.decode("utf-8", errors="ignore") or "").strip()
            detail = err_text or out_text or "Codex CLI failed"
            if "401 Unauthorized" in detail or "status 401" in detail:
                raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": detail})
            raise HTTPException(status_code=500, detail={"code": "codex_error", "message": detail})

        thread_id = None
        final_text = ""
        usage = None
        saw_event = False
        for line in stdout.decode("utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            saw_event = True
            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id") or thread_id
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    final_text = item.get("text") or final_text
            if event.get("type") == "turn.completed":
                usage = event.get("usage") or usage
            if event.get("type") == "turn.failed":
                err = (event.get("error") or {}).get("message") or "Codex turn failed"
                if "401" in err:
                    raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": err})
                raise HTTPException(status_code=500, detail={"code": "codex_error", "message": err})

        if not saw_event and err_text:
            if "401 Unauthorized" in err_text or "status 401" in err_text:
                raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": err_text})
            if "Error:" in err_text or "Fatal error" in err_text:
                raise HTTPException(status_code=500, detail={"code": "codex_error", "message": err_text})
        if not saw_event and not final_text:
            out_text = (stdout.decode("utf-8", errors="ignore") or "").strip()
            if out_text:
                raise HTTPException(status_code=500, detail={"code": "codex_error", "message": out_text})

        return {"threadId": thread_id or request.threadId, "finalResponse": final_text, "usage": usage}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


@router.post("/api/codex/cli/stream")
async def codex_agent_cli_stream(request: CodexRequest, http_request: Request):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Message is required"})
    if not feature_enabled("codex"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Codex is disabled"})

    user = await require_user_from_request(http_request)
    message = _with_codex_agent_prefix(request.message)

    base_args = ["codex", "exec", "--json", "--color", "never", "--sandbox", request.sandboxMode or "workspace-write"]
    if request.approvalPolicy:
        base_args += ["--config", f'approval_policy="{request.approvalPolicy}"']
    if request.model:
        base_args += ["--model", request.model]
    base_args += ["--cd", safe_user_workdir(user, request.workingDirectory), "--skip-git-repo-check"]

    if request.threadId:
        base_args += ["resume", request.threadId, message]
    else:
        base_args += [message]

    env = os.environ.copy()
    if request.apiKey:
        env["OPENAI_API_KEY"] = request.apiKey
        env["CODEX_API_KEY"] = request.apiKey
        if request.baseUrl:
            env["OPENAI_BASE_URL"] = request.baseUrl

    async def gen():
        proc = await asyncio.create_subprocess_exec(
            *base_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        thread_id = None
        final_text = ""
        usage = None

        async def emit(obj: dict):
            yield (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                raw = line.decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except Exception:
                    async for b in emit({"type": "log", "message": raw}):
                        yield b
                    continue

                if event.get("type") == "thread.started":
                    thread_id = event.get("thread_id") or thread_id
                if event.get("type") == "item.completed":
                    item = event.get("item") or {}
                    if item.get("type") == "agent_message":
                        final_text = item.get("text") or final_text
                if event.get("type") == "turn.completed":
                    usage = event.get("usage") or usage
                if event.get("type") == "turn.failed":
                    err = (event.get("error") or {}).get("message") or "Codex turn failed"
                    async for b in emit({"type": "error", "message": err}):
                        yield b
                    break

                async for b in emit(event):
                    yield b
        except asyncio.CancelledError:
            # Client disconnected (e.g. user pressed Stop). Ensure the subprocess doesn't keep running.
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass
            raise
        finally:
            try:
                await proc.wait()
            except Exception:
                pass
            try:
                err_text = (await proc.stderr.read()).decode("utf-8", errors="ignore").strip()
            except Exception:
                err_text = ""
            if proc.returncode != 0 and err_text:
                async for b in emit({"type": "stderr", "message": err_text, "returnCode": proc.returncode}):
                    yield b

            async for b in emit(
                {
                    "type": "done",
                    "threadId": thread_id or request.threadId,
                    "finalResponse": final_text,
                    "usage": usage,
                    "returnCode": proc.returncode,
                }
            ):
                yield b

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("/api/codex/mcp")
async def codex_mcp_list(http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "MCP is disabled"})
    _ = await require_user_from_request(http_request)
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "mcp",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"servers": []}
        text = stdout.decode("utf-8", errors="ignore")
        servers = []
        for line in text.splitlines():
            name = (line.split() or [""])[0].strip()
            if name and name.lower() != "name":
                servers.append(name)
        return {"servers": servers}
    except Exception:
        return {"servers": []}


@router.get("/api/codex/mcp/details")
async def codex_mcp_details(http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "MCP is disabled"})
    _ = await require_user_from_request(http_request)
    try:
        servers_resp = await codex_mcp_list(http_request)
        names = servers_resp.get("servers", []) if isinstance(servers_resp, dict) else []
        details = []
        for name in names:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "codex",
                    "mcp",
                    "get",
                    name,
                    "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode != 0:
                    continue
                details.append(json.loads(stdout.decode("utf-8", errors="ignore")))
            except Exception:
                continue
        return {"servers": details}
    except Exception:
        return {"servers": []}


@router.get("/api/codex/login/status")
async def codex_login_status(http_request: Request):
    if not feature_enabled("codex"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Codex is disabled"})
    _ = await require_user_from_request(http_request)
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        text = stdout.decode("utf-8", errors="ignore").strip()
        err = stderr.decode("utf-8", errors="ignore").strip()
        combined = text or err
        logged_in = "Logged in" in combined
        return {"loggedIn": logged_in, "statusText": combined, "exitCode": proc.returncode}
    except Exception as e:
        return {"loggedIn": False, "statusText": str(e), "exitCode": None}


@dataclass
class DeviceLoginAttempt:
    id: str
    proc: asyncio.subprocess.Process
    created_at: float
    url: str | None = None
    code: str | None = None
    output: list[str] = field(default_factory=list)
    done: bool = False
    returncode: int | None = None


async def _read_device_login_output(attempt: DeviceLoginAttempt) -> None:
    try:
        assert attempt.proc.stdout is not None
        while True:
            line = await attempt.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").rstrip("\n")
            attempt.output.append(text)
            if attempt.url is None and "auth.openai.com/codex/device" in text:
                attempt.url = "https://auth.openai.com/codex/device"
            if attempt.code is None:
                import re

                m = re.search(r"\b([A-Za-z0-9]{4,6}-[A-Za-z0-9]{4,6})\b", text)
                if m:
                    attempt.code = m.group(1).upper()
        await attempt.proc.wait()
    finally:
        attempt.done = True
        attempt.returncode = attempt.proc.returncode


@router.post("/api/codex/login/device/start")
async def codex_login_device_start(http_request: Request):
    if not feature_enabled("codex"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Codex is disabled"})
    _ = await require_user_from_request(http_request)
    async with http_request.app.state.device_login_lock:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "--device-auth",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        attempt_id = str(uuid.uuid4())
        attempt = DeviceLoginAttempt(
            id=attempt_id,
            proc=proc,
            created_at=asyncio.get_running_loop().time(),
        )
        http_request.app.state.device_login_attempts[attempt_id] = attempt
        asyncio.create_task(_read_device_login_output(attempt))
        return {"loginId": attempt_id}


@router.get("/api/codex/login/device/status")
async def codex_login_device_status(loginId: str, http_request: Request):
    if not feature_enabled("codex"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Codex is disabled"})
    _ = await require_user_from_request(http_request)
    attempt = http_request.app.state.device_login_attempts.get(loginId)
    if not attempt:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown loginId"})

    tail = attempt.output[-50:]
    status = "pending"
    if attempt.done:
        status = "success" if attempt.returncode == 0 else "failed"
    return {
        "loginId": attempt.id,
        "status": status,
        "url": attempt.url,
        "code": attempt.code,
        "outputTail": tail,
        "returnCode": attempt.returncode,
    }
