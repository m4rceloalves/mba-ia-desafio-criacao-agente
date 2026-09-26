"""Agente principal: recebe o morador e encaminha ao especialista."""

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm

from aurora.agentes._comum import CONFIG_GERACAO, REGRAS_SESSAO

INSTRUCAO = f"""\
Voce e o assistente virtual do Residencial Aurora, no aplicativo dos moradores.

{REGRAS_SESSAO}

Encaminhe cada pedido ao especialista certo usando transfer_to_agent:
- reservas: reservar, cancelar ou listar reservas de areas comuns e consultar datas livres.
- visitantes: autorizar a entrada de visitantes e listar visitantes autorizados.
- regulamento: duvidas sobre regras, horarios e normas do condominio.

Voce nao conhece as regras do condominio: toda duvida sobre regras vai para o especialista
regulamento. Nunca invente reservas, codigos ou autorizacoes. Se o pedido nao se encaixar
em nenhum especialista, explique brevemente o que o assistente pode fazer."""


def criar_recepcao(modelo: str | BaseLlm, especialistas: list[LlmAgent]) -> LlmAgent:
    return LlmAgent(
        name="recepcao",
        model=modelo,
        description="Agente principal do Residencial Aurora; recebe o morador e encaminha o pedido.",
        instruction=INSTRUCAO,
        sub_agents=especialistas,
        generate_content_config=CONFIG_GERACAO,
    )
