import os
import pty
import select
import subprocess
import struct
import fcntl
import termios
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI

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
        "supabase_key": os.environ.get("SUPABASE_KEY")
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
    content: str

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


@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
    # Create PTY
    master_fd, slave_fd = pty.openpty()
    
    # Start shell
    p = subprocess.Popen(
        ["/bin/bash"],
        preexec_fn=os.setsid,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
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

