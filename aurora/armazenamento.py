"""Armazenamento do condominio em SQLite: schema, restauracao e repositorio."""

import contextlib
import datetime
import json
import re
import secrets
import sqlite3
import unicodedata
from collections.abc import Iterator

from aurora import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
  numero TEXT PRIMARY KEY,
  morador TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS areas (
  id TEXT PRIMARY KEY,
  nome TEXT NOT NULL,
  taxa REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservas (
  codigo TEXT PRIMARY KEY,
  apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
  area TEXT NOT NULL REFERENCES areas(id),
  data TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ativa', 'cancelada')),
  criada_em TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa_area_data
  ON reservas(area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
  nome TEXT NOT NULL,
  data TEXT NOT NULL,
  criada_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes_api (
  session_id TEXT PRIMARY KEY,
  apartamento TEXT NOT NULL,
  criada_em TEXT NOT NULL
);
"""

TENTATIVAS_CODIGO = 5
FORMATO_DATA = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def _agora() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


@contextlib.contextmanager
def _conectar() -> Iterator[sqlite3.Connection]:
    config.DIR_VAR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.CAMINHO_BANCO, timeout=10, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        con.execute("PRAGMA foreign_keys=ON")
        yield con
    finally:
        con.close()


@contextlib.contextmanager
def _transacao(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def _ler_json(nome: str) -> list[dict]:
    return json.loads((config.DIR_DADOS / nome).read_text(encoding="utf-8"))


def _carregar_estaticos(con: sqlite3.Connection) -> None:
    for apto in _ler_json("apartamentos.json"):
        con.execute(
            "INSERT INTO apartamentos (numero, morador) VALUES (?, ?) "
            "ON CONFLICT(numero) DO UPDATE SET morador = excluded.morador",
            (apto["numero"], apto["morador"]),
        )
    for area in _ler_json("areas.json"):
        con.execute(
            "INSERT INTO areas (id, nome, taxa) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET nome = excluded.nome, taxa = excluded.taxa",
            (area["id"], area["nome"], float(area["taxa"])),
        )


def _carregar_movimentos(con: sqlite3.Connection) -> None:
    agora = _agora()
    for reserva in _ler_json("reservas.json"):
        con.execute(
            "INSERT INTO reservas (codigo, apartamento, area, data, status, criada_em) "
            "VALUES (?, ?, ?, ?, 'ativa', ?)",
            (reserva["codigo"], reserva["apartamento"], reserva["area"], reserva["data"], agora),
        )
    for visitante in _ler_json("visitantes.json"):
        con.execute(
            "INSERT INTO visitantes (apartamento, nome, data, criada_em) VALUES (?, ?, ?, ?)",
            (visitante["apartamento"], visitante["nome"], visitante["data"], agora),
        )


def _remover_banco(caminho) -> None:
    for sufixo in ("", "-wal", "-shm", "-journal"):
        arquivo = caminho.with_name(caminho.name + sufixo)
        arquivo.unlink(missing_ok=True)


def restaurar() -> None:
    """Apaga os bancos (dados e sessoes) e recarrega o estado inicial de dados/."""
    _remover_banco(config.CAMINHO_BANCO)
    _remover_banco(config.CAMINHO_SESSOES)
    with _conectar() as con:
        con.executescript(SCHEMA)
        with _transacao(con):
            _carregar_estaticos(con)
            _carregar_movimentos(con)


def inicializar() -> None:
    """Garante o schema sem apagar nada; carrega os dados iniciais se o banco estiver vazio."""
    with _conectar() as con:
        con.executescript(SCHEMA)
        with _transacao(con):
            vazio = con.execute("SELECT COUNT(*) FROM apartamentos").fetchone()[0] == 0
            _carregar_estaticos(con)
            if vazio:
                _carregar_movimentos(con)


def resumo() -> dict:
    """Contagens das tabelas, para o comando de restauracao."""
    with _conectar() as con:
        return {
            tabela: con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            for tabela in ("apartamentos", "areas", "reservas", "visitantes")
        }


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().replace("-", " ").replace("_", " ").split())


def data_valida(data: str) -> bool:
    """Indica se a data esta exatamente no formato AAAA-MM-DD e existe no calendario."""
    if not isinstance(data, str) or not FORMATO_DATA.fullmatch(data):
        return False
    try:
        datetime.date.fromisoformat(data)
    except ValueError:
        return False
    return True


def _exigir_data(data: str) -> None:
    if not data_valida(data):
        raise ValueError(f"data fora do formato AAAA-MM-DD: {data!r}")


def listar_areas() -> list[dict]:
    with _conectar() as con:
        linhas = con.execute("SELECT id, nome, taxa FROM areas ORDER BY id").fetchall()
    return [dict(linha) for linha in linhas]


def resolver_area(texto: str) -> dict | None:
    """Aceita o id exato ou o nome da area, sem diferenciar caixa e acentos."""
    alvo = _normalizar(texto or "")
    if not alvo:
        return None
    areas = listar_areas()
    for area in areas:
        if alvo in (_normalizar(area["id"]), _normalizar(area["nome"])):
            return area
    candidatas = [
        area
        for area in areas
        if alvo in _normalizar(area["id"])
        or alvo in _normalizar(area["nome"])
        or _normalizar(area["id"]) in alvo
    ]
    return candidatas[0] if len(candidatas) == 1 else None


def apartamento_existe(numero: str) -> bool:
    with _conectar() as con:
        return con.execute("SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)).fetchone() is not None


def listar_reservas(apartamento: str) -> list[dict]:
    with _conectar() as con:
        linhas = con.execute(
            "SELECT codigo, area, data FROM reservas "
            "WHERE apartamento = ? AND status = 'ativa' ORDER BY data, codigo",
            (apartamento,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def data_disponivel(area: str, data: str) -> bool:
    _exigir_data(data)
    with _conectar() as con:
        ocupada = con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area, data),
        ).fetchone()
    return ocupada is None


def _novo_codigo() -> str:
    return f"RSV-{secrets.token_hex(4).upper()}"


def criar_reserva(apartamento: str, area: str, data: str) -> dict:
    """Grava a reserva; a exclusividade e decidida pelo indice ux_reserva_ativa_area_data."""
    _exigir_data(data)
    with _conectar() as con:
        for _ in range(TENTATIVAS_CODIGO):
            codigo = _novo_codigo()
            try:
                with _transacao(con):
                    con.execute(
                        "INSERT INTO reservas (codigo, apartamento, area, data, status, criada_em) "
                        "VALUES (?, ?, ?, ?, 'ativa', ?)",
                        (codigo, apartamento, area, data, _agora()),
                    )
            except sqlite3.IntegrityError as erro:
                mensagem = str(erro)
                if "reservas.codigo" in mensagem:
                    continue
                if "reservas.area" in mensagem and "reservas.data" in mensagem:
                    return {"status": "recusada", "motivo": "ja_reservada"}
                raise
            return {"status": "reservada", "codigo": codigo}
    raise RuntimeError("nao foi possivel gerar um codigo de reserva inedito")


def cancelar_reserva(
    apartamento: str,
    area: str | None = None,
    data: str | None = None,
    codigo: str | None = None,
) -> dict:
    """Cancela uma reserva ativa do apartamento informado, e somente dele."""
    if data:
        _exigir_data(data)
    filtros = ["apartamento = ?", "status = 'ativa'"]
    parametros: list[str] = [apartamento]
    for coluna, valor in (("area", area), ("data", data), ("codigo", codigo)):
        if valor:
            filtros.append(f"{coluna} = ?")
            parametros.append(valor)
    if len(parametros) == 1:
        return {"status": "nao_encontrada"}
    where = " AND ".join(filtros)
    with _conectar() as con:
        with _transacao(con):
            linhas = con.execute(
                f"SELECT codigo, area, data FROM reservas WHERE {where} ORDER BY data", parametros
            ).fetchall()
            if len(linhas) != 1:
                return {"status": "nao_encontrada" if not linhas else "ambigua"}
            alvo = dict(linhas[0])
            con.execute(
                "UPDATE reservas SET status = 'cancelada' "
                "WHERE codigo = ? AND apartamento = ? AND status = 'ativa'",
                (alvo["codigo"], apartamento),
            )
    return {"status": "cancelada", **alvo}


def listar_visitantes(apartamento: str) -> list[dict]:
    with _conectar() as con:
        linhas = con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def autorizar_visitante(apartamento: str, nome: str, data: str) -> dict:
    _exigir_data(data)
    with _conectar() as con:
        with _transacao(con):
            con.execute(
                "INSERT INTO visitantes (apartamento, nome, data, criada_em) VALUES (?, ?, ?, ?)",
                (apartamento, nome, data, _agora()),
            )
    return {"status": "autorizado", "nome": nome, "data": data}


def registrar_sessao(session_id: str, apartamento: str) -> None:
    with _conectar() as con:
        with _transacao(con):
            con.execute(
                "INSERT INTO sessoes_api (session_id, apartamento, criada_em) VALUES (?, ?, ?)",
                (session_id, apartamento, _agora()),
            )


def apartamento_da_sessao(session_id: str) -> str | None:
    with _conectar() as con:
        linha = con.execute(
            "SELECT apartamento FROM sessoes_api WHERE session_id = ?", (session_id,)
        ).fetchone()
    return linha["apartamento"] if linha else None
