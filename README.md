# Altair Assistant

Open-source AI desktop assistant with voice interaction, automation, and engineering tools.

Altair é um assistente de inteligência artificial open-source desenvolvido em Python, projetado para atuar como uma interface inteligente entre o usuário e o computador. O projeto combina interação por voz, integração com modelos de linguagem, automação de tarefas do sistema e ferramentas voltadas para matemática, física e engenharia.

O objetivo do Altair é criar uma plataforma modular e extensível capaz de auxiliar em tarefas técnicas, aprendizado e experimentação com inteligência artificial.

---

## Demo



---

## Funcionalidades
- Interação por voz  
  Escuta via Whisper e responde por TTS (Piper / ElevenLabs), com opção de ativar ou desativar fala pela interface.
- Chat desktop em tempo real  
  Interface com histórico de conversa, atalhos de mídia (copiar resposta, anexar arquivos, pré-visualização de imagens).
- Automação do sistema operacional  
  Abre aplicativos, executa comandos locais, realiza buscas web, abre sites e organiza arquivos.
- Automação do WhatsApp Web  
  Envia mensagens, arquivos e áudios gerados pelo próprio assistente usando pipeline interno (Piper → ogg).
- API remota (FastAPI)  
  Permite controlar o Altair a partir de dispositivos móveis ou outros sistemas.
- Geração CAD / 3D  
  Criação de modelos 3D como engrenagens, sólidos geométricos e sistemas mecânicos a partir de comandos em linguagem natural.
- Cálculos científicos avançados  
  • resolução de equações e sistemas  
  • integrais e derivadas  
  • gráficos de funções  
  • busca de raízes  
  • simulações físicas (lançamento oblíquo, oscilações)  
- Clima e geolocalização  
  • temperatura  
  • sensação térmica  
  • vento  
  • distância entre cidades  
  • mapa  
- Memória e análise de arquivos  
  • leitura de documentos  
  • extração de conteúdo  
  • resumos  
  • consultas inteligentes  
- Configuração dinâmica  
  • escolha de modelo LLM  
  • configuração de voz  
  • inicialização automática com o Windows

---

## Tecnologias

O Altair integra diversas tecnologias modernas:
- Python
- FastAPI
- Whisper (speech-to-text)
- Piper TTS
- ElevenLabs TTS
- CadQuery (CAD paramétrico)
- Node.js (automação WhatsApp Web)
- bibliotecas científicas Python

---

## Estrutura do projeto

```
.
├── src/
│   └── altair/
│       ├── __main__.py
│       ├── main.py
│       ├── core/
│       └── app/
│
├── scripts/
│   └── whatsapp/
│       └── teste.js
│
├── configs/
│   ├── apps.json
│   └── ...
│
├── data/
│   ├── audios_temp/
│   ├── json/
│   ├── models/
│   └── wwebjs_logs/
│
├── assets/
│   └── piper/
│
├── requirements.txt
├── package.json
└── package-lock.json
```

---

## Instalação:

Clone o repositório:
```
git clone https://github.com/gilberto-eng/altair-ai-assistant
cd altair-assistant
```

Instale as dependências Python:
```
pip install -r requeriments.txt
```

Execute o Altair:
```
python -m altair
```

Ou use o entrypoint recomendado:
```
python run_altair.py
```

---

## Automação do WhatsApp Web:

O servidor Node inicia automaticamente quando necessário.  
Logs são armazenados em:  
data/wwebjs_logs

Para executar manualmente:
```
node scripts/whatsapp/teste.js
```

---

## Configuração

Arquivos principais de configuração:
- configs/apps.json — aplicativos registrados
- data/json/*.json — configurações internas
- data/models/ — modelos locais

Variáveis de ambiente suportadas:
ALTAIR_WWEBJS_DIR  
ALTAIR_CHROME_PROFILE_DIR  
ALTAIR_DATA_DIR

---

## Roadmap

Planejamento de evolução do projeto:
- Interface de chat desktop
- Interação por voz
- Automação do sistema
- Automação WhatsApp Web
- API remota
- Sistema de plugins
- Integração com mais modelos locais
- Controle remoto mobile completo
- Visualização CAD integrada

⸻

## Visão do projeto

O Altair busca evoluir como um assistente de inteligência artificial modular focado em automação, ciência e engenharia. A proposta é permitir uma interação mais natural e poderosa com o computador por meio de voz, linguagem natural e ferramentas computacionais avançadas.

⸻

## Contribuição

Contribuições são bem-vindas.

Se quiser contribuir:
1. Faça um fork do projeto
2. Crie uma branch para sua feature
3. Abra um pull request

⸻

## Licença

Este projeto é distribuído sob a licença MIT.
:::
