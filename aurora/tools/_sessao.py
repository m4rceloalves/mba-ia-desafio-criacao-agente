"""Acesso ao apartamento dono da sessao."""

from google.adk.tools.tool_context import ToolContext

CHAVE_APARTAMENTO = "apartamento"


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    """Apartamento gravado no state na criacao da sessao; nunca vem do modelo."""
    apartamento = tool_context.state.get(CHAVE_APARTAMENTO)
    if not apartamento:
        raise RuntimeError("sessao sem apartamento definido")
    return str(apartamento)
