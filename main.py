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
    sandboxMode: Optional[str] = "read-only"
    approvalPolicy: Optional[str] = "never"
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None

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
        "workingDirectory": os.path.dirname(__file__),
    }

    try:
        env = os.environ.copy()
        if request.apiKey:
            env["CODEX_API_KEY"] = request.apiKey
            env["OPENAI_API_KEY"] = request.apiKey
        if request.baseUrl:
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
            raise HTTPException(
                status_code=500,
                detail=(stderr.decode("utf-8", errors="ignore") or "Codex agent failed"),
            )
        return json.loads(stdout.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
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
                         winsize = struct.pack("HHHH", int(rows), int(cols), 0, 0)
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
