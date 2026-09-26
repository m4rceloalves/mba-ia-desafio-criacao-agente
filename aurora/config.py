"""Configuracao do projeto: caminhos, nome da aplicacao e modelo."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")

if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"

DIR_DADOS = RAIZ / "dados"
DIR_VAR = RAIZ / "var"
CAMINHO_BANCO = DIR_VAR / "condominio.sqlite3"
CAMINHO_SESSOES = DIR_VAR / "sessoes_adk.sqlite3"

APP_NAME = "residencial_aurora"
MODELO = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
MODELO_FAKE = os.environ.get("AURORA_MODELO_FAKE", "")
