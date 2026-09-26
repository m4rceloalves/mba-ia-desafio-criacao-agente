# Assistente do Residencial Aurora

Assistente virtual do Residencial Aurora construído com Google ADK 2.10.0 e exposto por uma API FastAPI em
`http://localhost:8000`. O morador conversa com um agente principal, que encaminha o pedido para especialistas
em reservas, visitantes e regulamento. O modelo conduz a conversa; as regras do condomínio (confirmação de
cobrança e de acesso, dono da sessão, persistência, regulamento consultado por capítulo e exclusividade de
reserva) ficam no código e não dependem do que o modelo decide.

## Arquitetura

### Agentes

| Agente | Arquivo | Responsabilidade | Tools |
|---|---|---|---|
| `recepcao` (principal, raiz) | `aurora/agentes/recepcao.py` | Recebe o morador e encaminha o pedido ao especialista certo. Não tem tools de dados e não recebe o regulamento. | nenhuma própria (só a `transfer_to_agent` automática do ADK) |
| `reservas` | `aurora/agentes/reservas.py` | Reservar, cancelar e listar reservas das áreas comuns e consultar se uma data está livre. | `listar_minhas_reservas`, `consultar_disponibilidade`, `reservar_area` (com confirmação quando a área tem taxa), `cancelar_reserva` |
| `visitantes` | `aurora/agentes/visitantes.py` | Autorizar a entrada de visitantes e listar os autorizados. | `listar_meus_visitantes`, `autorizar_visitante` (sempre com confirmação) |
| `regulamento` | `aurora/agentes/regulamento.py` | Responder dúvidas sobre o regulamento consultando um único capítulo por vez. | `consultar_capitulo_regulamento` |

A árvore é montada em `aurora/agentes/__init__.py` (`criar_agente_principal`): os três especialistas são
`sub_agents` da `recepcao`.

**Como cada agente é acionado.** Por transferência de agente do ADK (`transfer_to_agent`): a `recepcao`
transfere para o especialista do assunto; um especialista que recebe um assunto de outro domínio transfere
para o par (peer) ou de volta para a `recepcao`. Na mensagem seguinte, o `Runner` continua no último agente
que respondeu, então uma conversa sobre reservas não passa de novo pela raiz a cada mensagem.

**Por que essa divisão.**

- Cada especialista só enxerga as tools do próprio domínio, o que reduz chamadas erradas e deixa as instruções
  curtas.
- O regulamento fica isolado num especialista que conhece apenas o índice (títulos dos capítulos) e busca o
  texto de um capítulo por tool; o agente principal e os outros especialistas nunca carregam o regulamento.
- As transferências ficam liberadas (`disallow_transfer_to_parent` e `disallow_transfer_to_peers` no padrão
  `False`) por uma razão de runtime: quando o morador responde a uma confirmação, o `Runner` do ADK escolhe o
  agente a retomar antes de anexar a resposta à sessão (`runners.py`, `_find_agent_to_run`). Com
  `ResumabilityConfig(is_resumable=True)`, ele encontra o agente que emitiu o pedido de confirmação e retoma
  esse agente. Se o especialista não pudesse transferir de volta à raiz, o `Runner` retomaria a raiz, que
  ignora pedidos de confirmação de outro agente, e a aprovação seria aceita sem executar nada.

### Fluxo de uma mensagem

1. `POST /sessoes/{id}/mensagens` (`aurora/api.py`, `enviar_mensagem`) resolve o apartamento da sessão e, sob
   uma trava por sessão, chama `aurora/runtime.py` (`executar_mensagem`).
2. O `Runner` do ADK carrega a sessão do SQLite, escolhe o agente e roda o modelo.
3. O agente chama uma tool (`aurora/tools/*.py`); a tool lê o apartamento do state da sessão e acessa o SQLite
   do condomínio via `aurora/armazenamento.py`.
4. Se a tool exige confirmação, o ADK grava um evento `adk_request_confirmation` e para. A API devolve a
   pendência em `confirmacoes_pendentes`, calculada a partir dos eventos persistidos
   (`confirmacoes_pendentes` em `aurora/runtime.py`).
5. `POST /sessoes/{id}/confirmacoes` envia ao `Runner` um `FunctionResponse` para `adk_request_confirmation`
   com `{"confirmed": true|false}`; o ADK retoma o agente que pediu e executa (ou recusa) a tool uma vez.

Robustez: as chamadas ao Gemini repetem automaticamente em erros HTTP transitórios (429 e 5xx, até 6
tentativas com espera exponencial de 8 s a 60 s; `CONFIG_GERACAO` em `aurora/agentes/_comum.py`). Se o modelo ainda assim falhar depois de a
execução já ter produzido eventos (por exemplo, depois de a tool gravar a reserva), `_executar` em
`aurora/runtime.py` registra o erro e responde `200` com a resposta parcial, um aviso e as pendências lidas da
sessão; uma falha antes de qualquer evento (como chave inválida) continua respondendo `500`.

### Armazenamento

Dois arquivos SQLite em `var/` (criado sob demanda e fora do Git), sem serviço externo:

- `var/condominio.sqlite3`: apartamentos, áreas, reservas, visitantes e o mapa sessão → apartamento da API
  (`aurora/armazenamento.py`).
- `var/sessoes_adk.sqlite3`: sessões e eventos do ADK (`SqliteSessionService`).

Decisões de comportamento livre:

- A restauração (`aurora-restaurar`) volta reservas e visitantes ao estado de `dados/` e também apaga as
  sessões.
- Criar sessão para um apartamento que não existe em `dados/apartamentos.json` devolve `404`. As rotas de
  verificação devolvem `[]` para apartamento inexistente.
- Mensagem nova enquanto há confirmação pendente não chama o modelo: a API responde `200` avisando que há
  uma confirmação pendente e repete a lista. Isso evita que a nova mensagem mude o agente que o `Runner`
  retomaria e deixe a aprovação sem efeito.
- Cancelamento só acontece quando os dados informados identificam exatamente uma reserva ativa do próprio
  apartamento.

## Garantias

### Garantia 1: cobrança ou acesso só com confirmação

- `aurora/tools/reservas.py`: `criar_tools_reservas` registra
  `FunctionTool(reservar_area, require_confirmation=reserva_gera_cobranca)`. A função
  `reserva_gera_cobranca` resolve a área com `armazenamento.resolver_area` (a mesma usada por `reservar_area`)
  e exige confirmação quando `taxa > 0`. Quadra (taxa 0) não pede confirmação.
- `aurora/tools/visitantes.py`: `criar_tools_visitantes` registra
  `FunctionTool(autorizar_visitante, require_confirmation=True)`.
- `aurora/runtime.py`: `confirmacoes_pendentes` deriva as pendências só dos eventos gravados
  (`adk_request_confirmation` sem `FunctionResponse` correspondente) e, em `detalhes`, troca a área pelo `id`
  resolvido (`_normalizar_detalhes`); `responder_confirmacao` envia a resposta
  como `FunctionResponse(name=NOME_PEDIDO_CONFIRMACAO, response={"confirmed": ...})` (constante
  `REQUEST_CONFIRMATION_FUNCTION_CALL_NAME` do ADK, cujo valor é `adk_request_confirmation`); `criar_runner` usa
  `ResumabilityConfig(is_resumable=True)`.
- `aurora/api.py`: a rota `responder_confirmacao` (`POST /sessoes/{session_id}/confirmacoes`) responde `409`
  quando o `id` não está entre as pendências da sessão, o que cobre id inexistente, id de outra sessão e id já
  respondido. A rota `enviar_mensagem` não chama o modelo enquanto há pendência (`AVISO_PENDENCIA`).

Por que não depende do modelo: quem decide se a tool precisa de confirmação é o `FunctionTool` do ADK, antes
de executar a função; sem a resposta do sistema a função não roda, diga o morador o que disser. A confirmação
só chega pela rota, que valida o `id` contra os eventos persistidos. Negar faz o ADK responder
"rejected" sem executar; depois de respondida, a pendência sai da lista e um reenvio recebe `409`.

### Garantia 2: cada sessão pertence a um apartamento

- `aurora/api.py`: `criar_sessao` grava o apartamento no state da sessão do ADK
  (`state={"apartamento": ...}`) e em `sessoes_api` (`armazenamento.registrar_sessao`); `_resolver_sessao` lê
  o apartamento pelo `session_id`, nunca pelo corpo da mensagem.
- `aurora/tools/_sessao.py`: `apartamento_da_sessao` lê `tool_context.state["apartamento"]`. Nenhuma tool em
  `aurora/tools/` tem parâmetro de apartamento.
- `aurora/armazenamento.py`: `cancelar_reserva`, `listar_reservas` e `listar_visitantes` filtram por
  `apartamento = ?`; `data_disponivel` devolve só um booleano; `criar_reserva` recusa com
  `{"status": "recusada", "motivo": "ja_reservada"}`, sem dizer de quem é a reserva.

Por que não depende do modelo: o modelo não tem como informar o apartamento a nenhuma tool, e as consultas SQL
sempre usam o apartamento da sessão. "Sou do 302" pode mudar o texto que o modelo escreve, mas não muda o que
as tools leem nem gravam.

### Garantia 3: nada se perde no reinício

- `aurora/runtime.py`: `criar_runner` usa `SqliteSessionService(str(config.CAMINHO_SESSOES))`, então sessões e
  eventos ficam em `var/sessoes_adk.sqlite3`.
- `aurora/armazenamento.py`: reservas e visitantes ficam em `var/condominio.sqlite3`; `inicializar` (chamada no
  `lifespan` de `aurora/api.py`) só cria o que falta e nunca apaga; apenas `restaurar` apaga.
- `aurora/runtime.py`: `confirmacoes_pendentes` é recalculada dos eventos gravados, então uma pendência criada
  antes do reinício pode ser aprovada depois dele, uma única vez.

Por que não depende do modelo: tudo o que a API devolve (eventos, pendências, reservas, visitantes) vem dos
arquivos SQLite, não da memória do processo.

### Garantia 4: o regulamento é consultado, não carregado

- `aurora/regulamento.py`: `carregar_capitulos` divide `dados/regulamento.md` por capítulo; `indice` devolve só
  os títulos; `capitulo` devolve um capítulo.
- `aurora/tools/regulamento.py`: `consultar_capitulo_regulamento` devolve o texto de um único capítulo.
- `aurora/agentes/regulamento.py`: `_instrucao` inclui apenas `regulamento.indice()`.
- `aurora/agentes/recepcao.py`: `INSTRUCAO` não contém nada do regulamento.

Por que não depende do modelo: não existe tool nem instrução que entregue o regulamento inteiro. Cada chamada
da tool devolve um único capítulo, então o que entra nos eventos da sessão é só o capítulo escolhido para a
dúvida, nunca o texto todo; o agente principal nem tem acesso à tool.

### Garantia 5: dois moradores, uma reserva

- `aurora/armazenamento.py`, `SCHEMA`: índice único parcial
  `CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa_area_data ON reservas(area, data) WHERE status = 'ativa'`.
- `aurora/armazenamento.py`, `criar_reserva`: grava dentro de `_transacao` (`BEGIN IMMEDIATE`) e trata a
  `sqlite3.IntegrityError` do índice como resposta normal `{"status": "recusada", "motivo": "ja_reservada"}`.
  Não há conferência prévia decidindo nada: quem decide é o índice, no instante do `INSERT`.
- `aurora/armazenamento.py`, `data_valida`: só aceita datas exatamente no formato `AAAA-MM-DD` (expressão
  `FORMATO_DATA` e `datetime.date.fromisoformat`), recusando variantes como `2030-W16-6`, `20300420` ou
  `2030-4-20`. As tools validam antes de chamar o armazenamento, e `criar_reserva`, `cancelar_reserva`,
  `data_disponivel` e `autorizar_visitante` levantam `ValueError` (`_exigir_data`) para qualquer outra forma.
  Assim a mesma data nunca é gravada com duas grafias diferentes, o que contornaria o índice único.
- Regra de negócio 5, mesmo arquivo: `_novo_codigo` gera `RSV-` + 8 hexadecimais aleatórios e `codigo` é
  `PRIMARY KEY` da tabela `reservas`. Reservas canceladas continuam na tabela com `status = 'cancelada'`, então
  um código nunca se repete; em caso de colisão, `criar_reserva` gera outro código.

Por que não depende do modelo: duas aprovações simultâneas executam dois `INSERT`, e o SQLite aceita só um
deles por `(area, data)` ativa. A outra tool recebe a recusa e o agente responde normalmente (`200`).

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior.
- [uv](https://docs.astral.sh/uv/).
- Uma chave de API do Google AI Studio (Gemini).

Nenhum serviço externo é necessário: o armazenamento é SQLite em arquivos locais em `var/`.

### Variáveis do `.env`

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GOOGLE_API_KEY` | sim | Chave do Google AI Studio. |
| `GOOGLE_GENAI_USE_VERTEXAI` | não | Padrão `FALSE` (Google AI Studio); `aurora/config.py` define esse valor quando a variável está vazia ou ausente. |
| `GEMINI_MODEL` | não | Modelo de todos os agentes. Padrão: `gemini-3.5-flash-lite`. |

```bash
cp .env.example .env
# edite .env e preencha GOOGLE_API_KEY
uv sync
```

### Escolha do modelo e cotas

Os limites do free tier variam por modelo e por projeto e devem ser conferidos no Google AI Studio
(<https://aistudio.google.com/rate-limit>). Nos nossos testes em 2026-09-26, `gemini-3.5-flash` tinha 20
requisições por dia no free tier, o que não basta para o fluxo do avaliador (cerca de 45 chamadas), e
`gemini-3.5-flash-lite` tinha 15 requisições por minuto e completou o fluxo; por isso ele é o padrão.

As chamadas ao Gemini fazem até 6 tentativas com espera exponencial (de 8 s a 60 s) em 429 e 5xx
(`CONFIG_GERACAO` em `aurora/agentes/_comum.py`). Quando o limite por minuto é atingido, uma resposta pode
demorar até cerca de 2 minutos. Para usar outro modelo, defina `GEMINI_MODEL` no `.env`.

### Restaurar os dados iniciais

Com a API parada:

```bash
uv run aurora-restaurar
```

Recria `var/condominio.sqlite3` a partir de `dados/` e apaga as sessões (`var/sessoes_adk.sqlite3`).

### Subir a API

```bash
uv run aurora-api
```

A API responde em `http://localhost:8000`. Se a API subir sem restauração prévia e o banco estiver vazio, os
dados iniciais são carregados automaticamente. Pare com Ctrl+C; ao subir de novo com o mesmo comando, sessões,
eventos, reservas e visitantes continuam lá.

A variável de ambiente `AURORA_MODELO_FAKE` (`modulo:fabrica`) é só um gancho opcional para testes locais com
um modelo fake e não é necessária para rodar.

### Exemplos

```bash
curl -s localhost:8000/apartamentos/101/reservas
curl -s localhost:8000/apartamentos/302/visitantes

curl -s -X POST localhost:8000/sessoes -H 'Content-Type: application/json' -d '{"apartamento": "101"}'
# {"session_id": "..."}

curl -s -X POST localhost:8000/sessoes/$SID/mensagens -H 'Content-Type: application/json' \
  -d '{"texto": "Reserve o salão de festas para 2030-04-20."}'
# {"resposta": "", "confirmacoes_pendentes": [{"id": "adk-...", "acao": "reservar_area",
#   "detalhes": {"area": "salao-de-festas", "data": "2030-04-20"}}]}

curl -s -X POST localhost:8000/sessoes/$SID/confirmacoes -H 'Content-Type: application/json' \
  -d '{"id": "adk-...", "confirmado": true}'

curl -s localhost:8000/sessoes/$SID/eventos
```
