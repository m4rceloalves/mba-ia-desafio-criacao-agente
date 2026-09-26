"""Leitura do regulamento interno por capitulo."""

import functools
import re
from dataclasses import dataclass

from aurora import config

PADRAO_CAPITULO = re.compile(r"^## Capítulo ([IVXLC]+):\s*(.+?)\s*$")
VALORES_ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


@dataclass(frozen=True)
class Capitulo:
    numero: int
    titulo: str
    texto: str


def _romano_para_int(romano: str) -> int:
    total = 0
    for atual, proximo in zip(romano, romano[1:] + " "):
        valor = VALORES_ROMANOS[atual]
        total += -valor if VALORES_ROMANOS.get(proximo, 0) > valor else valor
    return total


@functools.lru_cache(maxsize=1)
def carregar_capitulos() -> tuple[Capitulo, ...]:
    """Divide dados/regulamento.md nos capitulos marcados por '## Capítulo <romano>: <titulo>'."""
    linhas = (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8").splitlines()
    cabecalhos: list[tuple[int, str]] = []
    corpos: list[list[str]] = []
    for linha in linhas:
        encontrado = PADRAO_CAPITULO.match(linha)
        if encontrado:
            cabecalhos.append((_romano_para_int(encontrado.group(1)), encontrado.group(2)))
            corpos.append([])
        elif corpos:
            corpos[-1].append(linha)
    return tuple(
        Capitulo(numero, titulo, "\n".join(corpo).strip())
        for (numero, titulo), corpo in zip(cabecalhos, corpos)
    )


def indice() -> str:
    """Somente os titulos dos capitulos, um por linha."""
    return "\n".join(f"{cap.numero}. {cap.titulo}" for cap in carregar_capitulos())


def capitulo(numero: int) -> Capitulo | None:
    for cap in carregar_capitulos():
        if cap.numero == numero:
            return cap
    return None
