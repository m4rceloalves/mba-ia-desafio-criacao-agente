"""Arvore de agentes: recepcao (raiz) e especialistas."""

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm

from aurora.agentes.recepcao import criar_recepcao
from aurora.agentes.regulamento import criar_regulamento
from aurora.agentes.reservas import criar_reservas
from aurora.agentes.visitantes import criar_visitantes


def criar_agente_principal(modelo: str | BaseLlm) -> LlmAgent:
    especialistas = [
        criar_reservas(modelo),
        criar_visitantes(modelo),
        criar_regulamento(modelo),
    ]
    return criar_recepcao(modelo, especialistas)
