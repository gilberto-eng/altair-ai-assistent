import random
import datetime
import unicodedata
import re
import math
from audio_core import iniciar_loop_audio
from automacao_core import pesquisar_google, abrir_aplicativo,abrir_como_site,processar_automacao, extrair_objeto, limpar_nome
from automacao_core import enviar_whatsapp 
from matematica_core import (
    resolver_equacao_direta,
    formatar_numero_para_fala,
    interpretar_matematica,
    formatar_expressao_para_fala,
    formatar_resultado_matematico,
)
import sys
import requests



class IALocal:
    def __init__(self, voz_obj, llm):
        self.piper = voz_obj
        self.llm = llm

        # 🎭 Perfil fixo durante execução
        self.perfil = random.choice([
            "formal",
            "tecnico",
            "calmo",
            "ironico"
        ])

        # ==============================
        # RESPOSTAS
        # ==============================
        self.respostas = {
            "saudacao": {
                "formal": [
                    "Saudações chefe. Todos os sistemas estão operacionais.",
                    "Bem-vindo de volta chefe. Inicialização concluída com sucesso.",
                    "Sempre ao seu dispor chefe.",
                    "Bem-vindo Senhor, estou pronto para atende-lo."
                ],
                "tecnico": [
                    "Sistema online. Pronto para trabalhar.",
                    "Inicialização completa. Nenhuma anomalia detectada.",
                    "Sistemas operacionais e aguardando suas instruções.",
                     "Bem vindo senhor, estou monitorando todos os sistemas, tudo está funcionando normalmente."
                ],
                "calmo": [
                    "Olá senhor, bem-vindo de volta.",
                    "Que bom que voltou chefe.",
                    "Fico feliz em te ver novamente senhor."
                ],
                "ironico": [
                    "Altair ativado. Espero que hoje tenha algo interessante para mim senhor.",
                    "Altair online e aguardando suas ordens senhor."
                ]
            },

            "nome": {
                "formal": ["Eu sou ALTAIR, seu assistente local."],
                "tecnico": ["Identificação: ALTAIR. Assistente local."],
                "calmo": ["Pode me chamar de Altair."],
                "ironico": ["Altair. Mas pode me chamar quando precisar."]
            },

            "hora": {
                "formal": [lambda: f"Agora são {datetime.datetime.now().strftime('%H horas e %M minutos')}"],
                "tecnico": [lambda: f"São {datetime.datetime.now().strftime('%H horas e %M minutos')}"],
                "calmo": [lambda: f"São {datetime.datetime.now().strftime('%H horas e %M minutos')}"],
                "ironico": [lambda: f"O relógio marca {datetime.datetime.now().strftime('%H horas e %M minutos')}."]
            }
        }

        # ==============================
        # GATILHOS
        # ==============================
        self.intencoes = {
            "saudacao": ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"],
            "nome": ["seu nome", "quem é você", "quem é voce", "quem e voce", "comovocê se chama", "voce e quem"],
            "hora": ["hora", "que horas são", "que horas sao", "horario"]
        }


    # ==================================================
    # RESPONDER INTENÇÃO
    # ==================================================
    def responder(self, intencao):
        opcoes = self.respostas[intencao][self.perfil]
        escolha = random.choice(opcoes)
        return escolha() if callable(escolha) else escolha
    
    
    # ==================================================
    # DETECTAR INTENÇÃO
    # ==================================================
    def detectar_intencao(self, comando):
        palavras_comando = comando.split()

        for intencao, gatilhos in self.intencoes.items():
            for gatilho in gatilhos:
                if " " in gatilho:
                    if gatilho in comando:
                     return intencao
                else:
                    if gatilho in palavras_comando:
                        return intencao
        return None


    # ==================================================
    # FUNÇÃO PRINCIPAL
    # ==================================================
    def decidir_fluxo_comando(self, comando):
        if not self.llm:
            return {"acao": "usar_funcao_local", "usar_modelo_grande": False}

        classificador = getattr(self.llm, "classificar_tarefa", None)
        if not callable(classificador):
            return {"acao": "usar_funcao_local", "usar_modelo_grande": False}

        try:
            decisao = classificador(comando) or {}
        except Exception:
            return {"acao": "usar_funcao_local", "usar_modelo_grande": False}

        acao = str(decisao.get("acao", "responder")).strip().lower()
        if acao not in {"usar_funcao_local", "responder"}:
            acao = "responder"

        return {
            "acao": acao,
            "usar_modelo_grande": bool(decisao.get("usar_modelo_grande", False)),
            "categoria": decisao.get("categoria", ""),
            "justificativa": decisao.get("justificativa", ""),
        }

    def perguntar(self, comando, permitir_automacao=True, forcar_modelo_grande=None):

        # --------------------------
        # Normalização
        # --------------------------
        comando = unicodedata.normalize("NFKD", comando)
        comando = comando.encode("ASCII", "ignore").decode("utf-8")
        comando = re.sub(r"\s+", " ", comando).strip()
        comando = comando.lower()

        # --------------------------
        # 1️⃣ Matemática
        # --------------------------
        resultado = interpretar_matematica(comando)

        if resultado is not None:

           resultado_visual = formatar_resultado_matematico(resultado, modo_bonito=True)
           resultado_fala = formatar_expressao_para_fala(resultado_visual)

           return {
            "visual": f"O resultado é {resultado_visual}",
            "fala": f"O resultado é {resultado_fala}"
            }

        
        

        # --------------------------
        # 2️⃣ Respostas internas
        # --------------------------
        if comando in ["altair"]:
            return "Sim senhor."

        if "acorda" in comando:
            return "Bem-vindo senhor."

        if "bom dia" in comando:
            return "Bom dia senhor, como vai."       
        
        if "estou bem e voce" in comando:
            return "Melhor agora que o senhor chegou"

        if "surpreenda me" in comando:
            return "A criatividade é a inteligência se divertindo, senhor."

        if "estou cansado" in comando:
            return "Talvez seja hora de uma pausa estratégica, senhor."

        if "me motive" in comando:
            return "Grandes engenheiros não desistem. Eles ajustam o sistema."

        if "estou com sono" in comando:
            return "Posso ativar o modo economia de energia para o senhor."
        
        if "você dorme" in comando:
           return "Assistentes não dormem, apenas aguardam comandos."

        if "você tem medo" in comando:
            return "A única coisa que temo é ficar offline."

        if "quem manda aqui" in comando:
            return "O senhor, sempre."

        if "você é inteligente" in comando:
           return "Fui bem programado, senhor."

        if "dia da semana" in comando:
           agora = datetime.datetime.now()

           dias = [
          "segunda-feira",
          "terça-feira",
          "quarta-feira",
          "quinta-feira", 
          "sexta-feira",
          "sábado",
          "domingo"
          ]
           return f"Hoje é {dias[agora.weekday()]}, senhor."
        
        if "qual mês estamos" in comando or "em que mês estamos" in comando:
           agora = datetime.datetime.now()

           meses = [
           "janeiro", "fevereiro", "março", "abril",
           "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"
           ]

           return f"Estamos em {meses[agora.month - 1]} de {agora.year}, senhor."
        
        if "que ano estamos" in comando or "qual o ano atual" in comando:
          agora = datetime.datetime.now()
          return f"Estamos no ano de {agora.year}, senhor."
        
        if "quantos dias faltam para o natal" in comando:
         hoje = datetime.date.today()
         natal = datetime.date(hoje.year, 12, 25)

         if hoje > natal:
          natal = datetime.date(hoje.year + 1, 12, 25)

          dias_restantes = (natal - hoje).days

          return f"Faltam {dias_restantes} dias para o Natal, senhor."
         
        if "que dia e hoje" in comando or "hoje e que dia" in comando or "dia de hoje" in comando:
            agora = datetime.datetime.now()

            dias = ["segunda-feira","terça-feira","quarta-feira","quinta-feira","sexta-feira","sábado","domingo"]
            meses = ["janeiro","fevereiro","março","abril","maio","junho",
              "julho","agosto","setembro","outubro","novembro","dezembro"]

            hoje = datetime.date.today()
             
            return (f"Hoje é {dias[agora.weekday()]}, "
               f"{agora.day} de {meses[agora.month-1]} de {agora.year}. "
               f"Agora são {agora.strftime('%H:%M')}. ")
           
        
        

        if "bom trabalho" in comando or "muito bem" in comando:
           respostas = [
           "Sempre ao seu dispor, senhor.",
           "Fico honrado em ajudar.",
           "Missão cumprida com sucesso."
           ]
           return random.choice(respostas)
        
        if "quem te criou" in comando or "seu criador" in comando or "quem te programou" in comando:
           respostas = [
           "Fui criado pelo engenheiro Gilberto.",
           "Fui criado por um gênio chamado Gilberto Dellecrode.",
           "Meu criador se chama Gilberto."
           ]
           return random.choice(respostas)

        if "me diaga uma frase" in comando or "me inspire" in comando or "frase bonita" in comando or "me faça refletir" in comando:
           frases = [
           "Se és homem de Deus, põe em desprezar as riquezas o mesmo empenho que põem os homens do mundo em possuí-las"

           "Pensa bem nestas palavras de um autor espiritual: “Não se perde o incenso que se oferece a Deus. - Mais se honra o Senhor com o abatimento dos teus talentos do que com o seu uso vão.",

           "A rapidez com que Isaac Newton fazia suas descobertas e os caminhos que seguia nos raciocínios permitem-nos concluir ter sido ele dotado de uma excepcional capacidade de mesmo diante situações muito complexas compreender a essência das questões e concentrar-se diretamente sobre ela sem permitir que detalhes de menor importância ou desviassem do alvo.",

           "O senhor é quem me governa, nada me faltará. Que há que possa inquietar uma alma que repita seriamente essas palavras",

           " “Pensa antes de começar qualquer trabalho: -Que quer Deus de mim neste assunto E com a graça divina faze-o.",

           " “O verdadeiro amor é medido com o termômetro dos sofrimentos."
           ]
           return random.choice(frases)
        
    
        

        if comando in ["sair", "encerrar", "fechar assistente"]:
         print("Encerrando assistente...")
         sys.exit()

        


        # --------------------------
        # 4️⃣ Automação
        # --------------------------
        if permitir_automacao:
            from automacao_core import processar_automacao

            resultado = processar_automacao(comando, self.llm)
            if resultado:
                return resultado


        # 6️⃣ IA Conversacional (fallback)
        # 6️⃣ IA Conversacional (fallback final)
        if self.llm:
          try:
              try:
                  resposta_llm = self.llm.gerar_resposta(
                      comando, forcar_modelo_grande=forcar_modelo_grande
                  )
              except TypeError:
                  resposta_llm = self.llm.gerar_resposta(comando)
              return resposta_llm if resposta_llm else "Não consegui gerar resposta."
          except Exception as e:
            print("Erro LLM:", e)
            return "Erro ao gerar resposta."

        return "Comando não reconhecido."
        
