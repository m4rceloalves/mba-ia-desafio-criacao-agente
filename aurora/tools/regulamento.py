"""Tool de consulta ao regulamento interno, um capitulo por vez."""

from aurora import regulamento


async def consultar_capitulo_regulamento(numero: int) -> dict:
    """Devolve o texto de um unico capitulo do regulamento interno.

    Args:
      numero: numero do capitulo (1 a 14), conforme o indice.
    """
    capitulo = regulamento.capitulo(int(numero))
    if not capitulo:
        return {"status": "erro", "motivo": "capitulo_inexistente"}
    return {"numero": capitulo.numero, "titulo": capitulo.titulo, "texto": capitulo.texto}


def criar_tools_regulamento() -> list:
    return [consultar_capitulo_regulamento]
