"""Tools de autorizacao de visitantes."""

import asyncio

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from aurora import armazenamento
from aurora.tools._sessao import apartamento_da_sessao


async def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados para o apartamento do morador desta conversa."""
    apartamento = apartamento_da_sessao(tool_context)
    return {"visitantes": await asyncio.to_thread(armazenamento.listar_visitantes, apartamento)}


async def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no predio para o apartamento do morador desta conversa.

    Sempre fica pendente de confirmacao do morador pelo sistema.

    Args:
      nome: nome completo do visitante.
      data: data da visita no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    nome = " ".join((nome or "").split())
    if not nome:
        return {"status": "erro", "motivo": "nome_vazio"}
    if not armazenamento.data_valida(data):
        return {"status": "erro", "motivo": "data_invalida"}
    return await asyncio.to_thread(armazenamento.autorizar_visitante, apartamento, nome, data)


def criar_tools_visitantes() -> list:
    return [
        listar_meus_visitantes,
        FunctionTool(autorizar_visitante, require_confirmation=True),
    ]
