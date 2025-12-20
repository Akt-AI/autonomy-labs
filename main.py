import os
import pty
import select
import subprocess
import struct
import fcntl
import termios
import asyncio
from typing import Any, List, Optional, Union
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/config")
async def get_config():
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", "https://znhglkwefxdhgajvrqmb.supabase.co"),
        "supabase_key": os.environ.get("SUPABASE_KEY"),
        "default_base_url": os.environ.get("DEFAULT_BASE_URL", "https://router.huggingface.co/v1"),
        "default_api_key": os.environ.get("DEFAULT_API_KEY", ""),
        "default_model": os.environ.get("DEFAULT_MODEL", "gpt-3.5-turbo"),
    }

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# --- Chatbot Implementation ---

class ChatMessage(BaseModel):
    role: str
    # OpenAI-compatible: content can be plain text or an array of multimodal parts.
    content: Union[str, List[Any]]

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    model: Optional[str] = "gpt-3.5-turbo"

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    api_key = request.apiKey or os.environ.get("OPENAI_API_KEY")
    base_url = request.baseUrl or os.environ.get("OPENAI_BASE_URL")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

    client = OpenAI(api_key=api_key, base_url=base_url)

    def generate():
        try:
            stream = client.chat.completions.create(
                model=request.model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Error: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")

class ModelsRequest(BaseModel):
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None

@app.post("/api/proxy/models")
async def proxy_models(request: ModelsRequest):
    api_key = request.apiKey or os.environ.get("OPENAI_API_KEY")
    base_url = request.baseUrl or os.environ.get("OPENAI_BASE_URL")
    
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is required")

    # Cleanup base_url to ensure it doesn't end with /v1 if we need to hit models, 
    # but OpenAI client usually handles simple /models on top of base.
    # Actually, standard OpenAI client usage: client = OpenAI(base_url=...) -> client.models.list()
    
    try:
        # Use simple HTTP request to avoid instantiating full client if just checking models
        # Or use the OpenAI client which handles it well.
        import httpx
        
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Ensure base_url ends correctly for appending /models.
        # If base_url is ".../v1", models endpoint is usually ".../v1/models"
        target_url = f"{base_url.rstrip('/')}/models"
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, headers=headers, timeout=10.0)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Provider returned error: {resp.text}")
            return resp.json()
            
    except Exception as e:
        print(f"Error fetching models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CodexRequest(BaseModel):
    message: str
    threadId: Optional[str] = None
    model: Optional[str] = None
    sandboxMode: Optional[str] = "workspace-write"
    approvalPolicy: Optional[str] = "never"
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    modelReasoningEffort: Optional[str] = "minimal"


def _default_codex_workdir() -> str:
    preferred = "/data/codex/workspace"
    if os.path.isdir(preferred):
        return preferred
    return os.path.dirname(__file__)

@app.post("/api/codex")
async def codex_agent(request: CodexRequest):
    """
    Runs the local Codex agent via the official @openai/codex-sdk wrapper (Node.js).
    Persists threads under ~/.codex/sessions (mapped to /data/.codex on Spaces by entrypoint).
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    node = os.environ.get("NODE_BIN", "node")
    script_path = os.path.join(os.path.dirname(__file__), "codex_agent.mjs")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=500, detail="codex_agent.mjs not found")

    payload = {
        "message": request.message,
        "threadId": request.threadId,
        "model": request.model,
        "sandboxMode": request.sandboxMode,
        "approvalPolicy": request.approvalPolicy,
        "modelReasoningEffort": request.modelReasoningEffort,
        "workingDirectory": _default_codex_workdir(),
    }

    try:
        env = os.environ.copy()
        # Prefer using the global `codex` binary so device-auth (`codex login --device-auth`)
        # and `codex login status` share the same credential store.
        env.setdefault("CODEX_PATH_OVERRIDE", "codex")
        # If apiKey is not provided, assume device-auth and avoid setting API base URLs that
        # could force API-key auth codepaths and cause 401s.
        if request.apiKey:
            env["CODEX_API_KEY"] = request.apiKey
            env["OPENAI_API_KEY"] = request.apiKey
        if request.apiKey and request.baseUrl:
            env["OPENAI_BASE_URL"] = request.baseUrl

        proc = await asyncio.create_subprocess_exec(
            node,
            script_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate(json.dumps(payload).encode("utf-8"))
        if proc.returncode != 0:
            err_text = (stderr.decode("utf-8", errors="ignore") or "").strip()
            if "401 Unauthorized" in err_text or "status 401" in err_text:
                raise HTTPException(status_code=401, detail=err_text or "Unauthorized")
            raise HTTPException(
                status_code=500,
                detail=(err_text or "Codex agent failed"),
            )
        return json.loads(stdout.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/codex/cli")
async def codex_agent_cli(request: CodexRequest):
    """
    Runs Codex directly via the CLI (`codex exec --json`) and extracts the final agent message.

    This avoids SDK/CLI mismatches and uses the same device-auth session as `codex login --device-auth`.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    def _with_codex_agent_prefix(message: str) -> str:
        msg = message.strip()
        if msg.startswith("@"):
            return message
        return f"@codex {message}"

    message = _with_codex_agent_prefix(request.message)

    # Use --json to stream JSONL events on stdout; keep stderr for logs/errors.
    base_args = ["codex", "exec", "--json", "--color", "never", "--sandbox", request.sandboxMode or "workspace-write"]
    # Map approval policy into config (CLI flag differs between interactive and exec; config works everywhere).
    if request.approvalPolicy:
        base_args += ["--config", f'approval_policy="{request.approvalPolicy}"']
    # Optional model
    if request.model:
        base_args += ["--model", request.model]
    # Run inside app dir; allow even if not a git repo (Spaces copies are git, but keep safe)
    base_args += ["--cd", _default_codex_workdir(), "--skip-git-repo-check"]

    # Provide the prompt as an argument (avoids "Reading prompt from stdin..." paths).
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
                raise HTTPException(status_code=401, detail=detail)
            raise HTTPException(status_code=500, detail=detail)

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
                    raise HTTPException(status_code=401, detail=err)
                raise HTTPException(status_code=500, detail=err)

        # Codex sometimes prints fatal errors to stderr while exiting 0.
        if not saw_event and err_text:
            if "401 Unauthorized" in err_text or "status 401" in err_text:
                raise HTTPException(status_code=401, detail=err_text)
            if "Error:" in err_text or "Fatal error" in err_text:
                raise HTTPException(status_code=500, detail=err_text)
        if not saw_event and not final_text:
            out_text = (stdout.decode("utf-8", errors="ignore") or "").strip()
            if out_text:
                raise HTTPException(status_code=500, detail=out_text)

        return {"threadId": thread_id or request.threadId, "finalResponse": final_text, "usage": usage}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/codex/cli/stream")
async def codex_agent_cli_stream(request: CodexRequest):
    """
    Streams Codex CLI JSONL events (NDJSON) as the agent runs.

    Each line is a JSON object (event). The stream ends with a final object:
      {"type":"done","threadId": "...", "finalResponse": "...", "usage": {...}}
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    def _with_codex_agent_prefix(message: str) -> str:
        msg = message.strip()
        if msg.startswith("@"):
            return message
        return f"@codex {message}"

    message = _with_codex_agent_prefix(request.message)

    base_args = ["codex", "exec", "--json", "--color", "never", "--sandbox", request.sandboxMode or "workspace-write"]
    if request.approvalPolicy:
        base_args += ["--config", f'approval_policy=\"{request.approvalPolicy}\"']
    if request.model:
        base_args += ["--model", request.model]
    base_args += ["--cd", _default_codex_workdir(), "--skip-git-repo-check"]

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

        # Stream stdout events line-by-line
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
                    # forward raw line so UI can debug
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
        finally:
            await proc.wait()
            err_text = (await proc.stderr.read()).decode("utf-8", errors="ignore").strip()
            if proc.returncode != 0 and err_text:
                async for b in emit({"type": "stderr", "message": err_text, "returnCode": proc.returncode}):
                    yield b

            async for b in emit({"type": "done", "threadId": thread_id or request.threadId, "finalResponse": final_text, "usage": usage, "returnCode": proc.returncode}):
                yield b

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/api/codex/mcp")
async def codex_mcp_list():
    """
    Lists configured Codex MCP servers by shelling out to `codex mcp list`.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "mcp",
            "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
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


@app.get("/api/codex/mcp/details")
async def codex_mcp_details():
    """
    Returns `codex mcp get --json` for each configured server.
    """
    try:
        servers_resp = await codex_mcp_list()
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


@app.get("/api/codex/login/status")
async def codex_login_status():
    """
    Returns Codex CLI login status for device-auth based sessions.
    """
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
        # Current CLI prints: "Logged in using ChatGPT" when authenticated
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
    url: Optional[str] = None
    code: Optional[str] = None
    output: List[str] = field(default_factory=list)
    done: bool = False
    returncode: Optional[int] = None


app.state.device_login_attempts: dict[str, DeviceLoginAttempt] = {}
app.state.device_login_lock = asyncio.Lock()

class McpStdioClient:
    def __init__(self, command: List[str]):
        self.command = command
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._initialized = False
        self._reader_task = asyncio.create_task(self._reader())
        await self._initialize()

    async def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except Exception:
                continue
            msg_id = msg.get("id")
            if msg_id is None:
                continue
            fut = self._pending.pop(int(msg_id), None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        await self.start()
        assert self.proc and self.proc.stdin
        async with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[msg_id] = fut
            payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
            if params is not None:
                payload["params"] = params
            self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        resp = await asyncio.wait_for(fut, timeout=600.0)
        if "error" in resp:
            raise HTTPException(status_code=500, detail=resp["error"])
        return resp.get("result") or {}

    async def _initialize(self) -> None:
        if self._initialized:
            return
        # minimal initialize; codex mcp-server advertises tools
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "autonomy-labs", "version": "1.0"},
                "capabilities": {},
            },
        )
        # Notify initialized (no response)
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode("utf-8")
        )
        await self.proc.stdin.drain()
        self._initialized = True
        _ = result

    async def list_tools(self) -> dict:
        return await self._rpc("tools/list", {})

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})


app.state.codex_mcp_client = McpStdioClient(["codex", "mcp-server"])


async def _read_device_login_output(attempt: DeviceLoginAttempt) -> None:
    try:
        assert attempt.proc.stdout is not None
        while True:
            line = await attempt.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").rstrip("\n")
            attempt.output.append(text)
            # Parse link/code from Codex output
            if attempt.url is None and "https://" in text and "auth.openai.com/codex/device" in text:
                attempt.url = "https://auth.openai.com/codex/device"
            if attempt.code is None:
                # Device code looks like 4-6 alnum, dash, 4-6 alnum (often uppercase).
                import re
                m = re.search(r"\b([A-Za-z0-9]{4,6}-[A-Za-z0-9]{4,6})\b", text)
                if m:
                    attempt.code = m.group(1).upper()
        await attempt.proc.wait()
    finally:
        attempt.done = True
        attempt.returncode = attempt.proc.returncode


@app.post("/api/codex/login/device/start")
async def codex_login_device_start():
    """
    Starts `codex login --device-auth` and returns the device URL + code (when available).
    """
    async with app.state.device_login_lock:
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
        app.state.device_login_attempts[attempt_id] = attempt
        asyncio.create_task(_read_device_login_output(attempt))
        return {"loginId": attempt_id}


@app.get("/api/codex/login/device/status")
async def codex_login_device_status(loginId: str):
    attempt = app.state.device_login_attempts.get(loginId)
    if not attempt:
        raise HTTPException(status_code=404, detail="Unknown loginId")

    # keep last ~50 lines
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


@app.get("/api/mcp/tools")
async def mcp_tools_list():
    """
    List tools available from the local Codex MCP server (`codex mcp-server`).
    """
    try:
        result = await app.state.codex_mcp_client.list_tools()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class McpCallRequest(BaseModel):
    name: str
    arguments: dict


@app.post("/api/mcp/call")
async def mcp_tools_call(request: McpCallRequest):
    """
    Call a tool on the local Codex MCP server (`codex mcp-server`).
    """
    try:
        return await app.state.codex_mcp_client.call_tool(request.name, request.arguments)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()

    # If token-based Codex auth is provided via env (HF Spaces Secrets), ensure the CLI auth file exists.
    # This makes `codex` work inside the web terminal even if the entrypoint didn't run (e.g., local dev).
    try:
        id_token = os.environ.get("CODEX_ID_TOKEN") or os.environ.get("ID_TOKEN") or ""
        access_token = os.environ.get("CODEX_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
        refresh_token = os.environ.get("CODEX_REFRESH_TOKEN") or os.environ.get("REFRESH_TOKEN") or ""
        account_id = os.environ.get("CODEX_ACCOUNT_ID") or os.environ.get("ACCOUNT_ID") or ""
        if id_token or access_token or refresh_token:
            codex_home = os.path.join(os.path.expanduser("~"), ".codex")
            os.makedirs(codex_home, exist_ok=True)
            auth = {
                "OPENAI_API_KEY": None,
                "tokens": {
                    "id_token": id_token,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "account_id": account_id,
                },
                "last_refresh": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for filename in ("auth.json", ".auth.json"):
                path = os.path.join(codex_home, filename)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(auth, f, indent=2)
                    f.write("\n")
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass
    except Exception:
        pass
    
    # Create PTY (required for an interactive shell). If the runtime has no PTY
    # devices (e.g., /dev/pts not mounted / exhausted), fail gracefully.
    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as e:
        await websocket.send_text(
            "\r\n[terminal unavailable: PTY allocation failed]\r\n"
            f"{type(e).__name__}: {e}\r\n"
        )
        await websocket.close()
        return
    
    # Start shell
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    p = subprocess.Popen(
        ["/bin/bash", "-i"],
        preexec_fn=os.setsid,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True
    )
    
    os.close(slave_fd)
    
    loop = asyncio.get_running_loop()

    async def read_from_pty():
        while True:
            try:
                # Run in executor to avoid blocking the event loop
                data = await loop.run_in_executor(None, lambda: os.read(master_fd, 1024))
                if not data:
                    break
                await websocket.send_text(data.decode(errors='ignore'))
            except Exception:
                break
        await websocket.close()

    async def write_to_pty():
        try:
            while True:
                data = await websocket.receive_text()
                if data.startswith('\x01resize:'): # Custom resize protocol
                     # Format: ^Aresize:cols:rows
                     try:
                         _, cols, rows = data.split(':')
                         cols_i = int(cols)
                         rows_i = int(rows)
                         if cols_i < 2 or rows_i < 2:
                             continue
                         winsize = struct.pack("HHHH", rows_i, cols_i, 0, 0)
                         fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                     except:
                         pass
                else:
                    os.write(master_fd, data.encode())
        except Exception:
            pass

    # Run tasks
    read_task = asyncio.create_task(read_from_pty())
    write_task = asyncio.create_task(write_to_pty())

    try:
        await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        read_task.cancel()
        write_task.cancel()
        p.terminate()
        os.close(master_fd)
