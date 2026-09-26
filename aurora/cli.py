"""Comandos de linha: subir a API e restaurar os dados iniciais."""

import uvicorn

from aurora import armazenamento, config


def subir_api() -> None:
    uvicorn.run("aurora.api:app", host="127.0.0.1", port=8000)


def restaurar_dados() -> None:
    armazenamento.restaurar()
    contagens = armazenamento.resumo()
    print(f"Dados restaurados a partir de {config.DIR_DADOS}.")
    for tabela, total in contagens.items():
        print(f"  {tabela}: {total}")
    print("Sessões apagadas.")
