from threading import Lock
from typing import Callable, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

HTML_INTERFACE = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Altair Remote</title>
  <style>
    :root{
      --bg:#0e1116;
      --card:#171c25;
      --line:#2a3344;
      --txt:#e9eef8;
      --muted:#9fb0ca;
      --accent:#2f81f7;
      --accent2:#1f6feb;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family:"Segoe UI",Tahoma,sans-serif;
      background:
        radial-gradient(1000px 500px at 20% -10%, #1e2635 0%, transparent 60%),
        radial-gradient(800px 400px at 90% 110%, #17263f 0%, transparent 55%),
        var(--bg);
      color:var(--txt);
      min-height:100vh;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:16px;
    }
    .card{
      width:min(680px,100%);
      background:linear-gradient(180deg,#1b2130,#151a23);
      border:1px solid var(--line);
      border-radius:16px;
      padding:18px;
      box-shadow:0 15px 40px rgba(0,0,0,.35);
    }
    h1{
      margin:0 0 8px 0;
      font-size:1.2rem;
      letter-spacing:.5px;
    }
    p{
      margin:0 0 14px 0;
      color:var(--muted);
      font-size:.95rem;
    }
    .row{
      display:flex;
      gap:10px;
    }
    input[type="text"]{
      flex:1;
      border:1px solid var(--line);
      background:#0f141d;
      color:var(--txt);
      border-radius:10px;
      padding:12px;
      font-size:1rem;
      outline:none;
    }
    input[type="text"]:focus{border-color:var(--accent)}
    button{
      border:0;
      background:linear-gradient(180deg,var(--accent),var(--accent2));
      color:white;
      border-radius:10px;
      padding:0 16px;
      font-weight:600;
      min-width:110px;
      cursor:pointer;
    }
    .opt{
      margin-top:10px;
      color:var(--muted);
      font-size:.9rem;
      display:flex;
      align-items:center;
      gap:8px;
    }
    .box{
      margin-top:14px;
      border:1px solid var(--line);
      background:#0f141d;
      border-radius:10px;
      padding:12px;
      min-height:90px;
      white-space:pre-wrap;
      word-break:break-word;
    }
    .status{
      margin-top:10px;
      color:var(--muted);
      font-size:.85rem;
    }
  </style>
</head>
<body>
    <div class="card">
    <h1>ALTAIR Remote</h1>
    <p>Envie comandos de texto para o Altair rodando no seu PC.</p>
    <div class="row">
      <input id="cmd" type="text" placeholder="Digite um comando..." />
      <button id="send">Enviar</button>
    </div>
    <div class="row" style="margin-top:10px;">
      <input id="token" type="text" placeholder="Token (opcional)" />
    </div>
    <label class="opt">
      <input id="falar" type="checkbox" />
      Falar resposta no PC
    </label>
    <div id="resp" class="box">Aguardando comando...</div>
    <div id="status" class="status"></div>
  </div>

  <script>
    const cmd = document.getElementById("cmd");
    const send = document.getElementById("send");
    const resp = document.getElementById("resp");
    const status = document.getElementById("status");
    const falar = document.getElementById("falar");
    const tokenInput = document.getElementById("token");

    const params = new URLSearchParams(window.location.search);
    const tokenUrl = params.get("token");
    const tokenLocal = window.localStorage.getItem("altair_token");
    if (tokenUrl) {
      tokenInput.value = tokenUrl;
      window.localStorage.setItem("altair_token", tokenUrl);
    } else if (tokenLocal) {
      tokenInput.value = tokenLocal;
    }

    async function enviarComando() {
      const comando = cmd.value.trim();
      if (!comando) return;
      status.textContent = "Enviando...";
      send.disabled = true;
      try {
        const token = tokenInput.value.trim();
        if (token) {
          window.localStorage.setItem("altair_token", token);
        }
        const r = await fetch("/comando", {
          method: "POST",
          headers: {
            "Content-Type":"application/json",
            ...(token ? { "Authorization": `Bearer ${token}`, "X-Altair-Token": token } : {})
          },
          body: JSON.stringify({comando, falar: falar.checked})
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "Falha na requisicao.");
        resp.textContent = data.resposta || "(sem resposta)";
        cmd.value = "";
        status.textContent = "OK";
      } catch (e) {
        resp.textContent = "Erro ao enviar comando.";
        status.textContent = String(e);
      } finally {
        send.disabled = false;
      }
    }

    send.addEventListener("click", enviarComando);
    cmd.addEventListener("keydown", (e) => {
      if (e.key === "Enter") enviarComando();
    });
  </script>
</body>
</html>
"""


class ComandoRequest(BaseModel):
    comando: str
    falar: bool = False


class ComandoResponse(BaseModel):
    resposta: str
    fala: str


def criar_api_app(
    processar_comando_altair: Callable[[str, bool], Dict[str, str]],
    api_lock: Lock,
    token: Optional[str] = None,
) -> FastAPI:
    api_app = FastAPI(title="Altair Remote API", version="1.0.0")
    token_normalizado = (token or "").strip()

    def _validar_token(request: Request) -> None:
        if not token_normalizado:
            return
        auth = (request.headers.get("authorization") or "").strip()
        header_token = (request.headers.get("x-altair-token") or "").strip()
        query_token = (request.query_params.get("token") or "").strip()
        if auth.lower().startswith("bearer "):
            auth = auth[7:].strip()
        if token_normalizado in {auth, header_token, query_token}:
            return
        raise HTTPException(status_code=401, detail="Token invalido ou ausente.")

    @api_app.get("/", response_class=HTMLResponse)
    def interface_web() -> str:
        return HTML_INTERFACE

    @api_app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @api_app.post("/comando", response_model=ComandoResponse)
    def comando_api(payload: ComandoRequest, request: Request) -> Dict[str, str]:
        _validar_token(request)
        with api_lock:
            resultado = processar_comando_altair(payload.comando, falar=payload.falar)
        return {"resposta": resultado.get("visual", ""), "fala": resultado.get("fala", "")}

    return api_app


def iniciar_api_remota(api_app: FastAPI, host: str = "0.0.0.0", port: int = 8000) -> None:
    uvicorn.run(api_app, host=host, port=port, log_level="info")
