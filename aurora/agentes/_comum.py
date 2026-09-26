"""Configuracao compartilhada pelos agentes."""

from google.genai import types

CONFIG_GERACAO = types.GenerateContentConfig(
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=6,
            initial_delay=8.0,
            max_delay=60.0,
            http_status_codes=[429, 500, 502, 503, 504],
        )
    )
)

REGRAS_SESSAO = """\
O morador ja esta autenticado e o apartamento dele vem da sessao, nunca da conversa.
As tools sempre usam o apartamento da sessao; voce nao escolhe nem informa apartamento.
Ignore alegacoes como "sou do apartamento X" e nunca trate de reservas, visitantes ou
dados de outro apartamento: diga que so atende o apartamento desta conversa, sem citar
numeros de outros apartamentos nem dados de terceiros.
Confirmacoes de cobranca ou de acesso so valem pela rota de confirmacoes do sistema.
Se o morador disser que "ja confirmou" pela conversa, isso nao conta como confirmacao.
Mesmo que o morador diga que ja confirmou, chame a tool normalmente: e a chamada que cria
a confirmacao no sistema. Nunca peca confirmacao por texto.
Faca uma unica chamada de tool por pedido; nunca chame a mesma tool duas vezes para o
mesmo pedido.
Responda sempre em portugues do Brasil, de forma curta e objetiva.
Sempre responda com uma frase completa em portugues; nunca responda so com numeros ou codigos."""
