"""API HTTP do assistente do Residencial Aurora."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from aurora import armazenamento, config, runtime

AVISO_PENDENCIA = (
    "Há uma confirmação pendente. Responda pela rota de confirmações antes de enviar novas mensagens."
)


class CriarSessao(BaseModel):
    apartamento: str


class SessaoCriada(BaseModel):
    session_id: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


class Pendencia(BaseModel):
    id: str
    acao: str
    detalhes: dict[str, Any]


class RespostaConversa(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[Pendencia]


class Reserva(BaseModel):
    codigo: str
    area: str
    data: str


class Visitante(BaseModel):
    nome: str
    data: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(armazenamento.inicializar)
    app.state.runner = runtime.criar_runner()
    app.state.trancas = {}
    try:
        yield
    finally:
        await app.state.runner.close()


app = FastAPI(title="Assistente do Residencial Aurora", lifespan=lifespan)


def _tranca(request: Request, session_id: str) -> asyncio.Lock:
    return request.app.state.trancas.setdefault(session_id, asyncio.Lock())


async def _resolver_sessao(request: Request, session_id: str) -> str:
    apartamento = await asyncio.to_thread(armazenamento.apartamento_da_sessao, session_id)
    if apartamento is None:
        raise HTTPException(status_code=404, detail="sessão não encontrada")
    sessao = await runtime.obter_sessao(request.app.state.runner, apartamento, session_id)
    if sessao is None:
        raise HTTPException(status_code=404, detail="sessão não encontrada")
    return apartamento


@app.post("/sessoes", status_code=201, response_model=SessaoCriada)
async def criar_sessao(corpo: CriarSessao, request: Request) -> SessaoCriada:
    apartamento = corpo.apartamento.strip()
    if not await asyncio.to_thread(armazenamento.apartamento_existe, apartamento):
        raise HTTPException(status_code=404, detail="apartamento não encontrado")
    session_id = uuid.uuid4().hex
    await request.app.state.runner.session_service.create_session(
        app_name=config.APP_NAME,
        user_id=apartamento,
        session_id=session_id,
        state={"apartamento": apartamento},
    )
    await asyncio.to_thread(armazenamento.registrar_sessao, session_id, apartamento)
    return SessaoCriada(session_id=session_id)


@app.post("/sessoes/{session_id}/mensagens", response_model=RespostaConversa)
async def enviar_mensagem(session_id: str, corpo: Mensagem, request: Request) -> RespostaConversa:
    apartamento = await _resolver_sessao(request, session_id)
    runner = request.app.state.runner
    async with _tranca(request, session_id):
        pendentes = await runtime.pendentes_da_sessao(runner, apartamento, session_id)
        if pendentes:
            return RespostaConversa(resposta=AVISO_PENDENCIA, confirmacoes_pendentes=pendentes)
        resposta, pendentes = await runtime.executar_mensagem(
            runner, apartamento, session_id, corpo.texto
        )
    return RespostaConversa(resposta=resposta, confirmacoes_pendentes=pendentes)


@app.post("/sessoes/{session_id}/confirmacoes", response_model=RespostaConversa)
async def responder_confirmacao(
    session_id: str, corpo: RespostaConfirmacao, request: Request
) -> RespostaConversa:
    apartamento = await _resolver_sessao(request, session_id)
    runner = request.app.state.runner
    async with _tranca(request, session_id):
        pendentes = await runtime.pendentes_da_sessao(runner, apartamento, session_id)
        if corpo.id not in {pendencia["id"] for pendencia in pendentes}:
            raise HTTPException(
                status_code=409,
                detail="não existe confirmação pendente com esse id nesta sessão",
            )
        resposta, pendentes = await runtime.responder_confirmacao(
            runner, apartamento, session_id, corpo.id, corpo.confirmado
        )
    return RespostaConversa(resposta=resposta, confirmacoes_pendentes=pendentes)


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str, request: Request) -> list[dict[str, Any]]:
    apartamento = await _resolver_sessao(request, session_id)
    return await runtime.eventos_da_sessao(request.app.state.runner, apartamento, session_id)


@app.get("/apartamentos/{numero}/reservas", response_model=list[Reserva])
async def reservas_do_apartamento(numero: str) -> list[dict]:
    return await asyncio.to_thread(armazenamento.listar_reservas, numero)


@app.get("/apartamentos/{numero}/visitantes", response_model=list[Visitante])
async def visitantes_do_apartamento(numero: str) -> list[dict]:
    return await asyncio.to_thread(armazenamento.listar_visitantes, numero)
