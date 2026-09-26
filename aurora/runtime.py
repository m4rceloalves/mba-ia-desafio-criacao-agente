"""Runner do ADK com sessao persistida e o protocolo de confirmacao de tools."""

import asyncio
import importlib
import logging

from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.flows.llm_flows.functions import (
    REQUEST_CONFIRMATION_FUNCTION_CALL_NAME as NOME_PEDIDO_CONFIRMACAO,
)
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from aurora import armazenamento, config
from aurora.agentes import criar_agente_principal

logger = logging.getLogger("aurora.runtime")

AVISO_FALHA_MODELO = (
    "Não consegui concluir a resposta agora; consulte suas reservas ou tente novamente."
)


def _modelo_configurado() -> str | BaseLlm:
    if not config.MODELO_FAKE:
        return config.MODELO
    modulo, _, fabrica = config.MODELO_FAKE.partition(":")
    return getattr(importlib.import_module(modulo), fabrica)()


def criar_runner(modelo: str | BaseLlm | None = None) -> Runner:
    config.DIR_VAR.mkdir(parents=True, exist_ok=True)
    app = App(
        name=config.APP_NAME,
        root_agent=criar_agente_principal(modelo or _modelo_configurado()),
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
    return Runner(app=app, session_service=SqliteSessionService(str(config.CAMINHO_SESSOES)))


def _normalizar_detalhes(pendencia: dict) -> dict:
    detalhes = pendencia["detalhes"]
    area = detalhes.get("area")
    if pendencia["acao"] == "reservar_area" and isinstance(area, str):
        encontrada = armazenamento.resolver_area(area)
        if encontrada:
            detalhes["area"] = encontrada["id"]
    return pendencia


def confirmacoes_pendentes(eventos: list[Event]) -> list[dict]:
    """Pedidos de confirmacao ainda sem resposta, derivados so dos eventos persistidos.

    Acessa o SQLite para normalizar a area; chamar via asyncio.to_thread em codigo async.
    """
    pendentes: dict[str, dict] = {}
    for evento in eventos:
        if not evento.content or not evento.content.parts:
            continue
        for parte in evento.content.parts:
            chamada = parte.function_call
            if chamada and chamada.name == NOME_PEDIDO_CONFIRMACAO and chamada.id:
                original = (chamada.args or {}).get("originalFunctionCall") or {}
                pendentes[chamada.id] = {
                    "id": chamada.id,
                    "acao": original.get("name", ""),
                    "detalhes": dict(original.get("args") or {}),
                }
            resposta = parte.function_response
            if resposta and resposta.name == NOME_PEDIDO_CONFIRMACAO and resposta.id:
                pendentes.pop(resposta.id, None)
    return [_normalizar_detalhes(pendencia) for pendencia in pendentes.values()]


def extrair_resposta(eventos: list[Event]) -> str:
    textos = []
    for evento in eventos:
        if evento.partial or not evento.content or evento.content.role != "model":
            continue
        for parte in evento.content.parts or []:
            if parte.text and not parte.thought:
                textos.append(parte.text.strip())
    return "\n".join(texto for texto in textos if texto)


def _tem_conteudo(evento: Event) -> bool:
    """O ADK emite um evento so com error_code antes de relancar a excecao; ele nao conta."""
    return evento.author != "user" and bool(evento.content and evento.content.parts)


async def _executar(
    runner: Runner, apartamento: str, session_id: str, mensagem: types.Content
) -> tuple[str, list[dict]]:
    novos: list[Event] = []
    falhou = False
    try:
        async for evento in runner.run_async(
            user_id=apartamento, session_id=session_id, new_message=mensagem
        ):
            novos.append(evento)
    except Exception:
        if not any(_tem_conteudo(evento) for evento in novos):
            raise
        logger.error(
            "execucao interrompida depois de %d eventos na sessao %s",
            len(novos),
            session_id,
            exc_info=True,
        )
        falhou = True
    resposta = extrair_resposta(novos)
    if falhou:
        resposta = "\n".join(texto for texto in (resposta, AVISO_FALHA_MODELO) if texto)
    return resposta, await pendentes_da_sessao(runner, apartamento, session_id)


async def executar_mensagem(
    runner: Runner, apartamento: str, session_id: str, texto: str
) -> tuple[str, list[dict]]:
    mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
    return await _executar(runner, apartamento, session_id, mensagem)


async def responder_confirmacao(
    runner: Runner, apartamento: str, session_id: str, id_confirmacao: str, confirmado: bool
) -> tuple[str, list[dict]]:
    mensagem = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=id_confirmacao,
                    name=NOME_PEDIDO_CONFIRMACAO,
                    response={"confirmed": confirmado},
                )
            )
        ],
    )
    return await _executar(runner, apartamento, session_id, mensagem)


async def obter_sessao(runner: Runner, apartamento: str, session_id: str):
    return await runner.session_service.get_session(
        app_name=config.APP_NAME, user_id=apartamento, session_id=session_id
    )


async def pendentes_da_sessao(runner: Runner, apartamento: str, session_id: str) -> list[dict]:
    sessao = await obter_sessao(runner, apartamento, session_id)
    return await asyncio.to_thread(confirmacoes_pendentes, sessao.events if sessao else [])


async def eventos_da_sessao(runner: Runner, apartamento: str, session_id: str) -> list[dict]:
    sessao = await obter_sessao(runner, apartamento, session_id)
    if not sessao:
        return []
    return [evento.model_dump(mode="json", exclude_none=True) for evento in sessao.events]
