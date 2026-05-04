from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionState:
    arquivo_selecionado_envio: Optional[str] = None

