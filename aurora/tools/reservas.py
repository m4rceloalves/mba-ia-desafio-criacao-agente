"""Tools de reservas das areas comuns."""

import asyncio

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from aurora import armazenamento
from aurora.tools._sessao import apartamento_da_sessao

ERRO_AREA = {"status": "erro", "motivo": "area_desconhecida"}
ERRO_DATA = {"status": "erro", "motivo": "data_invalida"}


async def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    apartamento = apartamento_da_sessao(tool_context)
    reservas = await asyncio.to_thread(armazenamento.listar_reservas, apartamento)
    nomes = {area["id"]: area["nome"] for area in await asyncio.to_thread(armazenamento.listar_areas)}
    return {
        "reservas": [
            {**reserva, "nome_area": nomes.get(reserva["area"], reserva["area"])}
            for reserva in reservas
        ]
    }


async def consultar_disponibilidade(area: str, data: str, tool_context: ToolContext) -> dict:
    """Informa se uma area esta livre em uma data (AAAA-MM-DD). Nao revela quem reservou.

    Args:
      area: id da area (salao-de-festas, churrasqueira ou quadra).
      data: data no formato AAAA-MM-DD.
    """
    apartamento_da_sessao(tool_context)
    encontrada = await asyncio.to_thread(armazenamento.resolver_area, area)
    if not encontrada:
        return ERRO_AREA
    if not armazenamento.data_valida(data):
        return ERRO_DATA
    livre = await asyncio.to_thread(armazenamento.data_disponivel, encontrada["id"], data)
    return {"area": encontrada["id"], "data": data, "disponivel": livre}


async def reserva_gera_cobranca(
    area: str = "", data: str = "", tool_context: ToolContext | None = None
) -> bool:
    """Decide, em codigo, se reservar_area precisa de confirmacao: area com taxa maior que zero."""
    encontrada = await asyncio.to_thread(armazenamento.resolver_area, area)
    return bool(encontrada and encontrada["taxa"] > 0 and armazenamento.data_valida(data))


async def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma area comum para o apartamento do morador desta conversa.

    Areas com taxa ficam pendentes de confirmacao do morador pelo sistema.

    Args:
      area: id da area (salao-de-festas, churrasqueira ou quadra).
      data: data no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    encontrada = await asyncio.to_thread(armazenamento.resolver_area, area)
    if not encontrada:
        return ERRO_AREA
    if not armazenamento.data_valida(data):
        return ERRO_DATA
    resultado = await asyncio.to_thread(
        armazenamento.criar_reserva, apartamento, encontrada["id"], data
    )
    if resultado["status"] != "reservada":
        return {**resultado, "area": encontrada["id"], "data": data}
    return {
        "status": "reservada",
        "codigo": resultado["codigo"],
        "area": encontrada["id"],
        "nome_area": encontrada["nome"],
        "data": data,
        "taxa": encontrada["taxa"],
    }


async def cancelar_reserva(
    tool_context: ToolContext, area: str = "", data: str = "", codigo: str = ""
) -> dict:
    """Cancela uma reserva ativa do apartamento do morador desta conversa, sem confirmacao.

    Informe o codigo ou a area e a data da reserva.

    Args:
      area: id da area (salao-de-festas, churrasqueira ou quadra), opcional.
      data: data da reserva no formato AAAA-MM-DD, opcional.
      codigo: codigo da reserva, opcional.
    """
    apartamento = apartamento_da_sessao(tool_context)
    area_id = None
    if area:
        encontrada = await asyncio.to_thread(armazenamento.resolver_area, area)
        if not encontrada:
            return ERRO_AREA
        area_id = encontrada["id"]
    if data and not armazenamento.data_valida(data):
        return ERRO_DATA
    return await asyncio.to_thread(
        armazenamento.cancelar_reserva,
        apartamento,
        area_id,
        data or None,
        codigo.strip().upper() or None,
    )


def criar_tools_reservas() -> list:
    return [
        listar_minhas_reservas,
        consultar_disponibilidade,
        FunctionTool(reservar_area, require_confirmation=reserva_gera_cobranca),
        cancelar_reserva,
    ]
