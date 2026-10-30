# Chat workspace and memory inspector

The default interface is a quiet conversation view with recent chats, suggested
starting points, a message composer, cancellation and light/dark themes. On small
screens the conversation menu collapses behind the menu button. This is an
original CookieAI interface inspired by restrained chat workspaces, not an OpenAI
product or a claim of affiliation.

The **Debug** button in the top-right opens the inspector. It is closed initially
and never opens automatically when related memories are found. Escape or the
close button returns to chat. Advanced Brief, Tasks, Skills and Privacy tools stay
available while Debug is open.

Inspector sections:

- **Process:** the actual latest turn state, worker status and saved pipeline.
- **Sessions:** authorized conversation history, with buttons to reopen a chat.
- **Memory:** current authorized source memories, including revision-aware
  controls to mark a memory shareable or return it to private ownership.
- **Sharing:** existing incoming/outgoing grants, explicit grant creation and
  revocation. A grant exposes only SHARED-marked memories; other users do not
  receive conversation history automatically.
- **Retrieval:** source IDs, context budget and heuristic session relationships.
- **Transfer:** the current session and saved context handoff metadata. It does
  not fabricate cross-agent transfers or claim queued stages have completed.
- **Connections:** effective model/embedding configuration and worker health.
  A configured provider is not labelled live-verified without an actual call.

Debug is an inspection interface, not an authorization bypass or administrator
role. Its API requests use the same authenticated namespace, agent and disclosure
checks as chat. It exposes no provider credentials or private reasoning traces.

## Actual answering path

```text
authenticated session -> durable turn queue -> existing worker
  -> authorized memory retrieval and context composition
  -> heuristic grouping of retrieved evidence by source session
  -> bounded, untrusted context -> configured assistant model
  -> final-answer validation -> response + context trace
  -> raw user-message retention and permitted existing learning stages
```

Session correlation now travels with the model's context rather than existing
only as a second client-side panel. It reuses authorized retrieved hits and does
not make an additional model request. Shared terms and entities establish
relevance, not causality. Existing source-revision and erasure checks remain.
Retrieval remains subject to the configured embedder; hash-test embeddings do not
establish semantic retrieval quality.

The normal UI sends raw turns, preserving exact source messages. It does not
silently enable extraction, background reflection, external connectors or Hermes
tool execution. Existing enabled worker stages still apply. External services
require a real adapter and authorization; this change does not invent connectors.

### Assistant capability description

The assistant now receives a trusted application capability contract, separately
from retrieved untrusted conversation text. It distinguishes the model's own
stateless inference from the application's persistent memory service. It must not
deny cross-session retrieval merely because the base LLM lacks internal storage.
The context identifies the current session explicitly so earlier sessions are not
misrepresented as messages from the current conversation.

The live workspace inspection found three completed turns over two sessions; its
latest turn referenced three memories and two related sessions. There were no
stored experiences or procedures, so no learned skill was available to reuse.
The skills retrieval path remains connected; ordinary chat alone is not promoted
to a verified reusable procedure. Handoff tasks and autonomous execution are
disabled in this bounded local runner.

After the correction, one live non-retained check confirmed persistent
cross-session memory support. Estimated ledger delta: $0.00017305. Nineteen
focused offline checks passed. Existing chat history, token and budget envelope
were preserved; old model replies remain historical and are not rewritten.

## Nemotron configuration

The explicitly requested live connection is running locally at
`http://127.0.0.1:8766`, alongside the synthetic preview on 8765. Use the private
workspace access token in `.chat-workspace/access-token.txt`; it differs from the
public synthetic preview token. The Token Factory API key stays server-side.

The real worker completed a minimal synthetic connection turn and Nemotron
returned `CONNECTED.`. See [connection evidence](chat-tokenfactory-connection.json)
for request counts and usage-based cost. Memory is persistent in the ignored
`.chat-workspace` directory and uses Qwen semantic embeddings. No production
database or personal transcripts were imported.

The stopped benchmark's authoritative ledger was transferred locally with all
prior requests, uncertain reservations and policy history preserved. The owned
benchmark VM was stopped to avoid idle compute charges; its disk remains retained.
Do not restart a separate cloud writer against an old copied ledger. The chat
workspace has an additional $0.25 allocation within the existing $20 parent cap;
its stored budget envelope prevents a restart from resetting that allowance.

To restart after a normal shutdown:

```powershell
.\.venv\Scripts\python.exe -m scripts.chat_workspace --billing-ledger .benchmark-artifacts\budget.sqlite3 --max-additional-cost-usd 0.25 --port 8766
```

It loads only the private `NEBIUS_API_KEY` from the environment or `.env.nebius`.
The API and worker share the same injected, metered model route. All semantic
embedding requests use the same ledger. Raw ingestion does not invoke an extraction
model; optional model-assisted task/extraction routes are disabled in this local
runner. Initial server startup makes no inference request until a user sends a
message. Earlier verification statements below describe the initial offline UI
pass; the subsequent explicit live connection is recorded separately above.

See [assistant.nebius.env.example](../config/assistant.nebius.env.example). Supply
the values privately to **both the API and worker**, then restart those existing
processes using the repository's normal deployment procedure:

```dotenv
MEMORY_ASSISTANT_PROVIDER_BASE_URL=https://api.tokenfactory.nebius.com/v1
MEMORY_ASSISTANT_PROVIDER_API_KEY=YOUR_PRIVATE_TOKEN_FACTORY_KEY
MEMORY_ASSISTANT_MODEL=nvidia/Nemotron-3_5-Lightning
MEMORY_ASSISTANT_COMPLETION_LIMIT_PARAMETER=max_completion_tokens
MEMORY_ASSISTANT_REASONING_EFFORT=none
MEMORY_ASSISTANT_OUTPUT_TOKENS=1024
```

The exact route above was previously discovered/live-tested in the benchmark;
availability and account access must still hold at runtime. This implementation
pass made no new paid inference calls. The configured model appears in the
header and Connections inspector.

Assistant URL/key/model are separate from extraction and embedding settings.
An explicitly selected assistant endpoint never inherits another provider's key
or chat-template thinking switch. Preserve the existing compatible embedding
identity and store; changing vector dimensions/model requires deliberate reindexing.
Existing namespace privacy restrictions continue to govern hosted calls.

Without assistant overrides, legacy deployments retain their existing provider
and extraction-model fallback. No production environment, hosted database,
benchmark deployment or Google Cloud resource was modified by this UI pass.
No benchmark score improvement is claimed.

## Local preview and verification

```powershell
.\.venv\Scripts\python.exe -m scripts.personal_demo
```

Open `http://127.0.0.1:8765` and use the intentionally public synthetic demo token
`cookieai-local-demo-only`. This preview is ephemeral, uses test embeddings and
has **no live model**; model replies can report unavailable. It is for inspecting
the interface and existing fixture workflows, not evidence of live Nemotron use.

Verified: 23 focused Python tests and 9 Node interface tests, Ruff and JavaScript
syntax checks, all static assets returning HTTP 200, unique HTML IDs and complete
JavaScript-to-element references. Tests include an injected provider round trip
with the exact Nemotron route and cross-session memory in its real context.

Visual browser verification was blocked: the computer-use tool could not verify
the current browser URL. No alternative automation bypass was attempted. Mobile
and theme rules are implemented, but visual screenshots are not claimed as verified.
