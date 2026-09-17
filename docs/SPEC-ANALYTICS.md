# BonviCall — Call analysis, phase 1: transcription and rubric scoring

**Who reads this:** every agent that builds phase 1 of the analysis pipeline, and
`qa-review` when reviewing it. It is the single source of truth for this work.
Cross-cutting rules are **not** repeated here — they live in
`docs/CONVENTIONS.md` (server, contract, errors, time, permissions, testing,
language) and `docs/CONVENTIONS-CLIENT.md` (panel). Where this document decides
something those files do not cover, it says so and says why.

Author: `plan-architect` · 2026-09-17.
Sources read before writing: `docs/SPEC.md` §3, §4, §6, §10, §11; `docs/CONVENTIONS.md`;
`docs/CONVENTIONS-CLIENT.md`; the running BonviCall server under `server/src/`;
and `../BonviZvonki/services/backend/src/modules/{ai,pipeline,scoring}` in full.
Every line count, file path and code claim below was read off disk, not remembered.

---

## 0. What this is, and what it is not

BonviCall records and stores calls. It does not yet read them. BonviZvonki — a
sibling product that was built, measured and never deployed — does: it sends a
recording to an ASR provider, sends the transcript and a 100-point rubric to an
LLM, validates the answer's arithmetic, and stores a score with the evidence
behind it. The client's decision is to bring that logic **into** BonviCall as new
modules. **Maximise copying; minimise rewriting; production is never at risk.**

**Phase 1, and only phase 1, is specified here:** for a call BonviCall already
holds, produce a transcript and a rubric score, store them, and show them on the
call detail page. Nothing else.

**What comes later — named, not specified:**

| Phase | What | Why not now |
|---|---|---|
| 2 | Analytics pages: per-agent and per-team score trends, block breakdown, the review queue as a working screen, transcript search | Needs a scored corpus to design against. Building charts over zero rows designs them wrong. |
| 2 | The **editable rubric**: `rubrics` table, versioning, admin CRUD, `extra_rules` | Phase 1 pins the rubric in code (§2.5). Every score already carries its `rubric_version`, so making it editable later does not invalidate what phase 1 produced. |
| 3 | Sales compliance (BonviZvonki `modules/sales`: SAP import, price-list conformance, off-policy deal detection) | Depends on data BonviCall does not hold. |
| 3 | The Telegram survey bot and client CSAT (`modules/surveys`, `services/bot`) | An entire second delivery channel. Its only phase-1 footprint is the review rule it feeds, which is left out (§1.4). |

Two ground rules hold throughout and are repeated because they are the ones an
implementer is most likely to trade away under time pressure:

1. **No existing table is altered.** Not one `ALTER TABLE ... ADD COLUMN` on
   `calls`, `call_audio`, `agents`, `registered_numbers` or `installations`.
   BonviZvonki writes the transcript onto `calls.transcript` and the stage onto
   `calls.status`; here both are new tables (§2).
2. **The feature is off in production until an admin turns it on.**
   `analysis.enabled` defaults to `false` (§4.4). Deploying phase 1 must be a
   no-op on the running system until somebody decides otherwise.

---

## 1. Copy map

This is the core of the document. Each row is one BonviZvonki file, its
destination in BonviCall, a verdict, and — for `copy + rewire` — the exact seams
that change. Line counts are `wc -l`; the `code` figure excludes blank lines and
comment/docstring lines and was produced by tokenising each file.

### 1.1 Destination layout

One new server module, `analysis`, owning four tables. It is added to the
release-1 module set of `CONVENTIONS.md` §3, which is a closed list — **that
amendment is part of this work and needs a line in `docs/ASSUMPTIONS.md`.**

```
server/src/modules/analysis/
├── __init__.py
├── models.py           NEW   four tables (§2)
├── schemas.py          NEW   panel wire schemas (§6)
├── service.py          NEW   AnalysisService — panel reads, queueing, status
├── rules.py            PORT  pure: review decision, na budget, word count
├── jobs.py             NEW   the four worker entry points (§5)
├── entities.py         PORT  stage outcomes, batch report, internal errors
├── config.py           PORT  the tuning knobs, read from app_settings
├── pipeline.py         PORT  the orchestrator: claim → transcribe → score → write
├── transcribe.py       PORT  stage 1
├── score.py            PORT  stage 2
├── limits.py           PORT  rate limiter, provider cooldown, backoff
├── scorer.py           PORT  transcript + rubric → validated draft
├── validator.py        PORT  recompute the arithmetic; never trust the model
├── prompt.py           PORT  the prompt — the product itself
├── rubric_default.py   PORT  the 100-point rubric, pinned in code for phase 1
├── score_writer.py     PORT  idempotent write of one score row
├── errors.py           PORT  provider error hierarchy + translation + redaction
├── registry.py         PORT  the provider registry — one entry per vendor
├── factory.py          PORT  settings + env → a configured client
├── providers/
│   ├── __init__.py
│   ├── types.py        PORT  ASRClient / LLMClient protocols, Transcript
│   ├── base.py         PORT  ClientConfig, collect_audio, guess_mime
│   ├── builders.py     PORT  client_kind → client class
│   ├── gemini.py       PORT
│   ├── openai_compat.py PORT
│   └── anthropic.py    PORT
└── tests/
    ├── test_analysis_api.py       RBAC 401/403/404 for three endpoints
    ├── test_analysis_rules.py     every function in rules.py
    ├── test_analysis_purity.py    prompt/validator/rubric_default import nothing
    ├── test_pipeline.py           idempotency, skip paths, stale reset
    ├── test_providers.py          request shape per provider, no key needed
    └── test_scoring.py            arithmetic, applicability, parsing, defects
```

**Why one module and not two (`ai` + `analysis`).** BonviZvonki separates them
and the separation is good. Here it costs more than it buys: a module with no
`models.py` must be declared in `server/src/core/reads.py` (`CONVENTIONS.md`
§2.1, §3), that file's stated purpose is aggregate cross-module reads, and
`tests/test_layering.py::test_cross_module_read_holders_never_write` then
forbids the substrings `insert(`, `update(`, `delete(` anywhere in the module's
top-level files — including `dict.update(` and `hashlib`'s `digest.update(`.
Stretching a fence built for `gaps` and `exports` around a vendor-SDK package,
and then tripping over a string match, is a worse outcome than a `providers/`
subpackage inside one module. Existing modules already carry files beyond the
canonical three (`audio/archive.py`, `audio/jobs.py`, `audio/reports.py`), so
this is the house shape, not a new one.

**Why the four-layer `domain/application/infrastructure/presentation` tree does
not come across:** `CONVENTIONS.md` §0 rejects it by name, with the evidence.
Directory depth is the one thing in this port that is deliberately flattened.

**Who calls what — the arrows, because four agents will otherwise draw four
different sets.**

```
api/panel/analysis.py ──► AnalysisService          (never anything else)
modules/analysis/jobs.py ──► pipeline.py ──► transcribe.py ──► providers/*
                                        └──► score.py ──► scorer.py ──► validator.py
                                                                  └──► prompt.py
pipeline.py ──► AudioService.analysis_source()     (the only way to audio, §3)
pipeline.py ──► CallService                        (never CallModel)
AnalysisService ──► CallService.get(principal, id) (scope is decided there, §6.2)
```

- **`AnalysisService` never calls a provider.** It reads rows, writes `queued`
  rows and reports status. Everything that costs money is behind `jobs.py`.
- **`pipeline.py` is never imported by anything under `api/`.** The check:
  `grep -rn "analysis.pipeline\|analysis import pipeline" server/src/api/` → empty.
- **`analysis` imports another module's *service*, never its models**
  (`CONVENTIONS.md` §2). It has a foreign key into `calls`, so
  `tests/test_layering.py` would permit `from src.modules.calls.models import
  CallModel` — do not use that permission for anything but the FK declaration in
  `models.py`. `CallService.get()` is what decides visibility, and re-deriving it
  here would put a second copy of the own-scope rule in the product.
- `rules.py`, `prompt.py`, `validator.py`, `rubric_default.py` and `entities.py`
  import nothing from `src`. They are the layer a test can exercise with no
  database, no session and no vendor key, and that property is what makes §9's
  1,324 ported scoring test lines run unchanged.

### 1.2 `modules/ai` — 1,917 lines, 1,225 of them code

| Source (`../BonviZvonki/services/backend/src/modules/`) | Lines (code) | Destination (`server/src/modules/analysis/`) | Verdict | Seams that change |
|---|---|---|---|---|
| `ai/__init__.py` | 1 (0) | — | do not port | Package marker; the destination has its own. |
| `ai/domain/entities.py` | 154 (86) | `providers/types.py` | **copy + rewire** (≈10 code lines) | `ROLE_ASR`/`ROLE_LLM` become aliases of `core.enums.AiRole.ASR/.LLM` — `AiRole` is a `StrEnum`, so `AiRole.ASR == "asr"` and every dict keyed by the old string constants keeps working untouched. Delete `ROLE_LABEL_UZ` (the panel's `uz.json` owns labels, `CONVENTIONS.md` §14). `ASRClient`/`LLMClient` protocols and `Transcript`/`TranscriptSegment` unchanged — `TranscriptSegment.confidence: float` is fine because it is never persisted (`CONVENTIONS.md` §10 forbids float **columns**). |
| `ai/domain/errors.py` | 460 (265) | `errors.py` | **copy + rewire** (≈45) | `AIError(AppError)` must **not** subclass `core.errors.AppError`: every `AppError` subclass in this product lives in `core/errors.py` (verified: `grep -rn "class .*Error(" src/modules/` is empty). Rebase the hierarchy on a local `class ProviderError(Exception)` keeping the attribute names `code`, `message`, `status_code` — `limits._status_of()` and `is_retryable()` read them by name and then copy unchanged. Uzbek message strings → English: these land in `call_analysis_state.failure_detail`, which the panel renders as technical detail beside the Uzbek headline keyed off `failure_code` (§7). `redact()` stays and gains the three env-held API keys. `translate()`, `retry_after_sec()`, `is_daily_quota()`, `human_delay()` copy as-is — they encode which vendor says "retry in 25s" in which field, which is knowledge that cost real 429s to acquire. |
| `ai/domain/registry.py` | 195 (109) | `registry.py` | **copy + rewire** (≈35) | Drop `api_key_setting`, `key_label_uz`, `legacy_key_settings`, `select_options()` — keys come from the environment (§4.2) and phase 1 has no provider-picker UI. Keep `env_var`, `client_kind`, `base_url`, `models`, `defaults`, `_assert_unique()`, `providers_for_role()`, `default_provider_key()`. **Keep both measured comments verbatim (translated):** Groq/Whisper is unusable for Uzbek (5 test calls, 5 zero scores) and the Gemini 2.x family is retired for new accounts while still appearing in `models.list`. Deleting those notes means paying to re-learn them. |
| `ai/application/factory.py` | 129 (86) | `factory.py` | **copy + rewire** (≈30) | `SettingsService(session).get_all_values()` does not exist here; BonviCall's `SettingsService` exposes `get`/`get_int`/`get_str`/`get_bool`/`get_list` and raises on a missing key. `resolve()` reads four keys by constant (`SettingKey.ANALYSIS_ASR_PROVIDER`, `…_ASR_MODEL`, `…_LLM_PROVIDER`, `…_LLM_MODEL`); the API key comes from `core.config.get_settings()`, never from the values dict. `resolve_from_values()` keeps its signature and stays database-free, so its test ports unchanged. |
| `ai/application/catalog.py` | 147 (94) | — | **do not port** | Live `GET /v1/models` per vendor. It exists to stop an admin picking a model the vendor retired — a real failure, but it only pays off behind the model-picker UI, which is phase 2. Porting it now ships a code path nothing calls. |
| `ai/application/tester.py` | 129 (98) | — | **do not port** | The settings page's "test this key" button; same reason. `ping()` stays on the clients (3 lines each) and is exercised by one manual-marked smoke test (§9). |
| `ai/infrastructure/builders.py` | 71 (47) | `providers/builders.py` | **copy as-is** (imports only, ≈8) | `BUILDERS` and `check_registry()` unchanged. `check_registry()` becomes an assertion in `test_providers.py`. |
| `ai/infrastructure/providers/base.py` | 123 (70) | `providers/base.py` | **copy + rewire** (≈10) | `collect_audio()`'s `MAX_AUDIO_MB = 200` guard stays but is now a second line of defence: the size is known from `call_audio.bytes` before a byte is read, so the pipeline refuses oversized audio without allocating (§3). `silence_wav()` and `guess_mime()` copy unchanged. |
| `ai/infrastructure/providers/gemini_provider.py` | 207 (146) | `providers/gemini.py` | **copy as-is** (imports only, ≈6) | The `_TRANSCRIBE_PROMPT` constant stays **in Uzbek** — see §1.6. `_SKIP`/`_RETIRED` model filters stay. |
| `ai/infrastructure/providers/openai_compat.py` | 199 (153) | `providers/openai_compat.py` | **copy as-is** (≈6) | — |
| `ai/infrastructure/providers/anthropic_provider.py` | 102 (71) | `providers/anthropic.py` | **copy as-is** (≈4) | — |
| `ai/tests/*` | 738 | see §9 | partial | `test_provider_requests.py` and `test_registry_and_factory.py` port; `test_settings_endpoint.py` does not. |

> **The provider list in the brief is stale, and the code is the authority.**
> The registry today holds **three** providers — `openai`, `gemini`,
> `anthropic`. `groq` and `elevenlabs` were removed with a 20-line comment
> recording why (Groq/Whisper produced Tibetan script and English "translations"
> for Uzbek speech across five real calls; ElevenLabs was dropped by the client
> and never tested). Both SDKs are still pinned in BonviZvonki's
> `requirements.txt`, which is what makes the stale list look current. Do not
> re-add either.

### 1.3 `modules/pipeline` — 2,993 lines, 1,736 of them code

| Source | Lines (code) | Destination | Verdict | Seams that change |
|---|---|---|---|---|
| `pipeline/application/deps.py` | 53 (28) | `pipeline.py` (top of file) | **copy + rewire** (≈10) | `PipelineDeps` survives — it is what lets the tests substitute ASR and LLM without a vendor key. `default_open_recording` (MoiZvonki stream) is deleted and replaced by `AudioService.analysis_source` (§3). Import `src.core.database.get_sessionmaker()`, not `SessionFactory`. |
| `pipeline/application/nightly.py` | 192 (75) | — | **do not port** | Its three steps are: pull from MoiZvonki (BonviCall's own device API and `api/telephony/webhook.py` already do ingestion), queue the day's calls (becomes the `analysis_dispatch` job, §5), send a Telegram digest (phase 3). Its one durable idea — re-queue *transient* failures over a window wider than the nightly one, because 885 rate-limited calls had gone permanently `failed` — survives as `select_transient_failures()` in `pipeline.py` and the `analysis_retry_transient` job. |
| `pipeline/application/orchestrator.py` | 601 (367) | `pipeline.py` | **copy + rewire** (≈150) | The heaviest rewire, and the one to read carefully before typing. **Deleted:** `CallLock` (Redis) — the worker's own advisory lock plus `SELECT … FOR UPDATE SKIP LOCKED` claiming replaces it (§5); `RouteStage` — BonviCall classifies `call_type` at ingest in `modules/calls/rules.py::classify_call_type` and re-runs it in the `reclassify_calls` job, so re-deriving it here would be a second implementation of a rule `CONVENTIONS.md` §7 already made singular; `call.status = CallStatus.*` — there is no such column, the state row *is* the status. **Changed:** `call.transcript` reads/writes become `CallTranscriptModel` rows; `NOT_SCORABLE_TYPES` becomes the gate in §2.6; `SessionFactory()` becomes `database.get_sessionmaker()()`. **Kept, and do not "simplify":** the `await session.commit()` at every stage boundary. Its two measured reasons still hold here — an intermediate stage invisible to other sessions, and rows locked for the 37 seconds a provider takes. Only the *third* justification (re-reading MoiZvonki settings) disappears with the audio source. |
| `pipeline/application/queue.py` | 364 (242) | `service.py` | **copy + rewire** (≈140: ≈80 rewired, ≈60 deleted) | **Deleted:** `enqueue_calls` (Celery `send_task`), `broker_depth` (Redis `llen`), `_inspect`/`worker_snapshot` (Celery `control.inspect`) — about 60 code lines of broker plumbing with no counterpart here. **Ported:** `db_snapshot` (stage counts, throughput, transient-waiting count), `reset_stale_running`, `recent_failures`, `full_status` — these are the status endpoint (§6). Keep the distinction `db_snapshot` draws between *failed* and *waiting for a quota to reset*: conflating them is why an admin once read 948 failures and concluded the system was broken when 885 were waiting. |
| `pipeline/application/route.py` | 97 (52) | — | **do not port** | See above: `call_type` is already BonviCall's, computed from the line directory at ingest. Its `DirectoryEmptyError` behaviour is preserved as the `call_type_unknown` skip reason (§2.4), which is the same decision — never guess, record why, self-heal when the directory fills. |
| `pipeline/application/runner.py` | 39 (18) | — | **do not port** | A sync→async bridge for Celery workers. BonviCall's worker is already an asyncio process (`server/src/worker.py`). |
| `pipeline/application/score.py` | 199 (150) | `score.py` | **copy + rewire** (≈45) | `RubricService(session).get_active()` → `rubric_default.DEFAULT_RUBRIC` and the pinned `RUBRIC_VERSION` (§2.5). `rubric.extra_rules` → `None` (phase 2). `agent_client_rating()` and the `client_rating` arguments to `decide()` are removed — they read the surveys tables, which are phase 3. `call.transcript` → the transcript row. `review.reasons` becomes `[{code, params}]` (§1.6). |
| `pipeline/application/tasks.py` | 103 (55) | — | **do not port** | Celery task definitions. Replaced by `jobs.py`, four functions with the `JobCallable` signature `async def (AsyncSession) -> int`. |
| `pipeline/application/transcribe.py` | 233 (153) | `transcribe.py` | **copy + rewire** (≈55) | See §3 in full. Summary: the MoiZvonki stream becomes a local-file stream; `_Counter`/`_counted` are deleted (the byte count is known from `call_audio.bytes`); the `_EXTENSION` content-type map is deleted (the container enum gives the extension directly); one of the two mid-stage `commit()` calls is deleted with its now-false comment; the cooldown pre-check **stays exactly where it is**, before the audio is opened. |
| `pipeline/domain/config.py` | 106 (48) | `config.py` | **copy + rewire** (≈35) | The dataclass and its per-field reasoning copy across; `from_env()` is replaced by `async def load_config(session)` reading `app_settings` by `SettingKey` constant. `core/settings_keys.py`'s own docstring makes this mandatory: "a value that is not a row in `app_settings` is a value nobody can change without a deploy". |
| `pipeline/domain/entities.py` | 315 (156) | `entities.py` | **copy + rewire** (≈70) | `PipelineStage` → `core.enums.AnalysisStage` (it is a database column, so it belongs in the enum catalogue, `CONVENTIONS.md` §10). `LOCKED` disappears — no lock state is persisted. The `PipelineError` subclasses become failure **codes** in `core.enums.AnalysisFailure`; the classes stay as internal exceptions carrying that code. `TRANSIENT_ERROR_CODES` becomes `TRANSIENT_FAILURES: frozenset[AnalysisFailure]` and keeps its deliberately narrow membership. `StageOutcome`, `CallOutcome` and `BatchReport` copy nearly unchanged; `BatchReport.not_sales` is renamed `not_scorable_type` for BonviCall's vocabulary. |
| `pipeline/infrastructure/limits.py` | 455 (222) | `limits.py` | **copy + rewire** (≈150: ≈85 rewired, ≈65 deleted) | **Deleted:** `get_redis`/`reset_redis` (≈35) and `CallLock` (≈30). **Rewired:** `RateLimiter` loses its Redis window counter and becomes an in-process sliding window — correct here rather than approximate, because the worker's advisory lock guarantees one `analysis_run` at a time (§5); `ProviderCooldown` moves from a Redis key with a TTL to the `ai_provider_cooldowns` table, which additionally survives a restart and is readable by the status endpoint — the thing an admin most needs when the queue stops. **Copied unchanged (≈90 lines, the valuable half):** `with_backoff`, `is_retryable`, `is_rate_limited`, `_wait_for`, `_status_of`. Their reasoning — ask the vendor how long to wait before guessing; retry 5xx as well as 429 because Gemini returns 503 under ordinary load; never retry a daily quota; never sleep longer than `max_wait_sec` inside a worker slot — is all still true. `cooldown_message()` moves to the panel's `uz.json`. |
| `pipeline/infrastructure/models.py` | 76 (47) | `models.py` (part) | **copy + rewire** (≈47, effectively rewritten) | The skeleton of `call_analysis_state`, plus its opening argument for why the state is a separate table rather than columns on `calls` — which is the same argument this document makes in §0 rule 1. Every column gains a `doc=` (`tests/test_model_registry.py::test_every_column_documents_itself`), the stage and error columns become PostgreSQL enums, and the cost columns are integers (§2.2). |
| `pipeline/presentation/router.py` | 160 (123) | `api/panel/analysis.py` | **copy + rewire** (≈75, mostly reference) | Shape is useful, details are not: `require_permission("agents:sync")` string literal → `Perm.ANALYSIS_RUN` constant (`CONVENTIONS.md` §11.2); `ValidationError`/`NotFoundError` from `src.core.errors` with an `ErrorCode`; Uzbek `Field(description=…)` → English (these become the OpenAPI document and therefore the panel's generated types); the free date-range `POST /run` is dropped in favour of the minimal surface of §6. |

### 1.4 `modules/scoring` — 2,913 lines, 1,866 of them code

| Source | Lines (code) | Destination | Verdict | Seams that change |
|---|---|---|---|---|
| `scoring/application/prompt.py` | 638 (432) | `prompt.py` | **copy as-is** (0 code lines) | Imports `typing.Any` and nothing else — it is already pure. This is the single biggest unchanged transfer in the port, and it is also the file that *is* the product: the rubric rendering, the `na` rules, the code-switching instruction, and the byte-stable system prompt that makes prompt caching possible. The only action is the language exception of §1.6. |
| `scoring/application/validator.py` | 782 (455) | `validator.py` | **copy + rewire** (≈35) | Two changes only. `ScoreValidationError(AppError)` → a local `ScoreInvalid(Exception)` carrying `.message`, because `rules.py`-adjacent files must not import framework or project error types and `AppError` subclasses live in `core/` (`CONVENTIONS.md` §2, §9); `score.py` catches it and records `AnalysisFailure.SCORE_INVALID`. Its ~25 Uzbek diagnostic strings become English — they are developer diagnostics shown as technical detail, not user-facing copy (§1.6). Everything else — the recomputed criterion→block→overall arithmetic, `_round_half_up` in the employee's favour, the `na` budget and the `MIN_APPLICABLE_POINTS` floor that closes the "mark everything not-applicable" loophole — copies verbatim. |
| `scoring/domain/rubric_default.py` | 259 (224) | `rubric_default.py` | **copy as-is** (0) | Imports `typing.Any`. The 100-point rubric, its four blocks, its criteria and their `optional` flags, and the red-flag table. Phase 1 pins it: `RUBRIC_VERSION = "v1"` (§2.5). |
| `scoring/application/scorer.py` | 152 (102) | `scorer.py` | **copy as-is** (≈8: imports and the exception name) | The invalid-response retry loop, including the detail that the **last** attempt relaxes the `na` budget rather than throwing away a paid-for answer, and flags `na_over_budget` instead. |
| `scoring/application/review_rules.py` | 178 (115) | `rules.py` | **copy + rewire** (≈35) | Thresholds and `count_words()` (which strips `[MM:SS]` and `SPEAKER_n:` so the short-transcript rule actually fires) copy unchanged. The Uzbek `message` in each reason is replaced by `{"code": …, "params": {…}}`; the panel's `uz.json` renders it. Rule 5 (client-survey gap) is removed with its two arguments — phase 3. `decide()` therefore takes `confidence`, `transcript_quality`, `transcript_text`, `duration_sec`, `red_flag_types`, `ai_score`, `na_over_budget`. |
| `scoring/application/score_writer.py` | 165 (94) | `score_writer.py` | **copy + rewire** (≈40) | `agent_client_rating()` (25 lines, reads `surveys`) is deleted. `_blocks_payload` and `_block_details_payload` copy unchanged — and their two warnings are load-bearing: `blocks` must stay a **flat** `{key: int}` (a nested object 500s the analytics cut and blanks the React page) and `_meta` must never land inside it. `confidence`/`cost_usd` become `confidence_pct`/`cost_micro_usd` integers (§2.2). |
| `scoring/domain/entities.py` | 94 (50) | `entities.py` (merged) | **copy + rewire** (≈20) | `ScoreBlock`, `BLOCK_MAX` (derived from the rubric, never hard-coded — they were once written twice and diverged 25 vs 15, producing a 167 % bar), `RedFlagType`, `RED_FLAG_PENALTY`, `Sentiment`, `ScoreSummary.grade` all copy. The `*_LABEL_UZ` dicts move to the panel's `uz.json`. `Sentiment` becomes `core.enums.CallSentiment` because it is a column. |
| `scoring/infrastructure/models.py` | 72 (41) | `models.py` (part) | **copy + rewire** (≈41, effectively rewritten) | Reference for `call_scores`: same JSONB columns and the same reasons for them. Rewritten for `Float`→integer, `doc=` on every column, enum columns, and the CHECK constraints of §2.2. |
| `scoring/application/rubric_service.py` | 199 (141) | — | **do not port** (phase 2) | Rubric CRUD, version bumping, the "blocks must total exactly 100" validator and the red-flag key regex. All of it is needed the day the rubric becomes editable; none of it is needed while it is a constant. |
| `scoring/application/rubric_upgrade.py` | 92 (48) | — | **do not port** (phase 2) | Migrates a stored rubric to a newer default. No stored rubric exists. |
| `scoring/infrastructure/rubric_models.py` | 64 (26) | — | **do not port** (phase 2) | The `rubrics` table, including the partial unique index that makes "exactly one active rubric" a database fact. Port it verbatim in phase 2; do not re-invent it. |
| `scoring/presentation/router.py` | 218 (138) | — | **do not port** (phase 2) | Rubric read/write endpoints. |

### 1.5 Totals

| | Lines | Code lines |
|---|---|---|
| The three modules, excluding tests | 7,823 | 4,827 |
| **Taken** (27 files) | **6,542** | **4,082** |
| Left behind (10 files + a package marker, §8) | 1,281 | 745 |

Of the 4,082 executable lines that come across:

| Bucket | Code lines | Share |
|---|---|---|
| **Copied unchanged** — imports adjusted at most | **2,972** | **73 %** |
| Rewired or deleted at a named seam | 1,110 | 27 % |

Plus **1,475 comment and docstring lines** to translate from Uzbek to English
(`CONVENTIONS.md` §14). That is mechanical work with no design decisions in it,
but it is not free and it is where a hurried port silently keeps a comment that
is no longer true — the MoiZvonki re-download argument in `with_backoff` being
the clearest example (§3). Roughly a tenth of those lines describe behaviour
being deleted and should go rather than be translated.

New code written from nothing — `models.py`, `schemas.py`, `service.py`'s panel
half, `jobs.py`, the panel router, the migration, the panel module — is
estimated at **≈900 lines**. Test work is §9.

**Read as a ratio: for every three lines of BonviZvonki logic that land
untouched, roughly one is edited and one is newly written.**

### 1.6 The language rule, and its one deliberate exception

`CONVENTIONS.md` §14 says Uzbek inside a `.py` file is legal in exactly one
place: `core/messages_uz.py`. Three ported files break that rule, and the
resolution is not "translate them".

**Decision: `modules/analysis/prompt.py` and `modules/analysis/rubric_default.py`
keep their Uzbek text and are added to §14's allow-list as the fourth and fifth
legal locations.** A model prompt is neither a comment nor a message a user
reads — it is domain data whose language is measured by the quality of the
output it produces on Uzbek and code-switched Uzbek/Russian speech. Translating
it into English would be an untested change to the product's most sensitive
input. The same holds for the rubric's criterion labels, which are what the
model matches against. `qa-review`'s §14 grep must be amended in the same pull
request, and the exception recorded in `docs/ASSUMPTIONS.md`.

**Everything else translates.** Comments, docstrings, provider error messages,
validator diagnostics and pipeline failure text all become English. User-facing
Uzbek moves where it belongs: `core/messages_uz.py` for the four new error codes
(§6.3) and `panel/src/shared/i18n/uz.json` for failure headlines, review-reason
sentences, block labels, red-flag labels and the cooldown notice. That is why
`review_rules` returns `{code, params}` and not a formatted sentence.

---

## 2. Data model

One migration, `010_create_analysis_schema`, creating five PostgreSQL enum types
and four tables, adding two values to the existing `alert_kind` enum, and seeding
the twenty-six `app_settings` rows of §4.6. **No `ALTER TABLE` on an existing
table.**

### 2.1 Enums — `server/src/core/enums.py`

Every one is bound with `pg_enum()` (`values_callable`, so PostgreSQL stores the
*value*, not the upper-case member name) and registered in `PG_ENUM_TYPES`.

| Type | Members | Notes |
|---|---|---|
| `analysis_stage` | `queued`, `transcribing`, `scoring`, `completed`, `skipped`, `failed` | BonviZvonki's `locked` is dropped: no lock state is persisted (§5). |
| `analysis_failure` | **Not analysable:** `no_audio`, `audio_expired`, `call_too_short`, `call_type_unknown`, `call_type_internal` · **Transient:** `provider_rate_limit`, `provider_cooldown`, `provider_unavailable`, `provider_network`, `interrupted`, `timeout` · **Permanent:** `transcript_empty`, `score_invalid`, `ai_not_configured`, `provider_auth`, `provider_model`, `sdk_missing`, `audio_too_large`, `internal` | 19 values, closed. `stage` says whether the row is terminal; this column says why. `internal` is the mapping of last resort for an exception the code did not foresee — the class name goes in `failure_detail`. A closed enum that cannot represent an unexpected failure would turn a surprise into a write error, which is the opposite of what it is for. |
| `ai_role` | `asr`, `llm` | The `ai_provider_cooldowns` primary key, and the value `ROLE_ASR`/`ROLE_LLM` alias (§1.2). |
| `call_sentiment` | `positive`, `neutral`, `negative` | |
| `transcript_quality` | `high`, `medium`, `low` | The model's own assessment of the transcript it was given; the review rule reads it. |

Two values are appended to the existing `alert_kind` enum with
`ALTER TYPE … ADD VALUE IF NOT EXISTS`, exactly as migration `008` does it:
`analysis_job_failed` and `analysis_cost_cap_reached` (§11.3).

> **Trap, and it will be hit at the end of the work if it is not handled first.**
> `tests/test_model_registry.py::test_migration_enum_table_matches_core_enums`
> reads the `PG_ENUMS` dict out of `001_create_release1_schema.py` **only**, then
> layers on `ALTER TYPE … ADD VALUE` statements found in later migrations, and
> asserts the result equals `PG_ENUM_TYPES` exactly. A new enum type created in
> migration 010 is invisible to it and the assertion fails. Fix the parser in
> the same task: make `_enum_values_from_migrations()` scan **every** migration
> for a `PG_ENUMS: dict[str, tuple[str, ...]] = {...}` block and merge them.
> Migration 010 therefore declares its own `PG_ENUMS` block in the same literal
> form, so a reviewer reads the enum values in the diff.

### 2.2 Tables

Every model is `class XModel(Base, UUIDMixin, TimestampMixin)` unless stated,
every column carries a `doc=`, every timestamp is `DateTime(timezone=True)`, and
**no column is a float** — three rules enforced by
`tests/test_model_registry.py`.

#### `call_transcripts` — one row per transcribed call

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4` | `UUIDMixin` |
| `call_id` | UUID | no | | FK `calls.id` `ON DELETE CASCADE`, **UNIQUE** |
| `text` | TEXT | no | | Verbatim, in the `[MM:SS] SPEAKER_0: …` form the prompt demands. The timestamps are not decoration: phase 2's click-a-line-to-seek and the red-flag timeline both read them. |
| `language` | VARCHAR(8) | yes | | What was asked of the provider (`analysis.asr_language`), or null when the provider was left to detect. |
| `provider` | VARCHAR(32) | no | | Registry key. |
| `model` | VARCHAR(64) | no | | |
| `char_count` | INTEGER | no | | Denormalised so a list can show size without loading the text. |
| `word_count` | INTEGER | no | | `rules.count_words()` — service tokens stripped. Stored because the review rule and the panel must agree on one number. |
| `audio_bytes` | BIGINT | no | | Bytes handed to the provider. Part of the cost measurement (§11.1). |
| `audio_duration_ms` | INTEGER | yes | | `call_audio.duration_ms` at transcription time. The ASR billing unit. |
| `asr_ms` | INTEGER | no | | Wall clock of the provider call. |
| `transcribed_at` | TIMESTAMPTZ | no | | |

Indexes: `uq_call_transcripts_call_id` (unique), `ix_call_transcripts_time` on
`transcribed_at DESC`. **No full-text index in phase 1** — transcript search is
phase 2, and an unused GIN index on a growing TEXT column is write cost for
nothing.

#### `call_scores` — one row per scored call

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `call_id` | UUID | no | | FK `calls.id` CASCADE, **UNIQUE** — one score per call, which is what makes re-running idempotent. |
| `overall_score` | SMALLINT | no | | CHECK `BETWEEN 0 AND 100`. |
| `blocks` | JSONB | no | `'{}'` | **Flat** `{block_key: int}`. Nothing nested, no `_meta`. |
| `block_details` | JSONB | no | `'{}'` | `{blocks: {...evidence per criterion...}, meta: {...}}` — how the number was reached, so "why 78?" is answerable without re-running. |
| `red_flags` | JSONB | no | `'[]'` | `[{type, severity, timestamp, quote}]`. |
| `outcome_signal` | JSONB | yes | | `{type, products, confidence}`. |
| `sentiment` | `call_sentiment` | yes | | |
| `transcript_quality` | `transcript_quality` | no | | |
| `coaching_note` | TEXT | yes | | |
| `confidence_pct` | SMALLINT | no | | 0–100. **Integer, not float** (`CONVENTIONS.md` §10): the value is compared against a threshold in Python, in SQL and in TypeScript. `review_rules.MIN_CONFIDENCE` becomes `70`. |
| `needs_review` | BOOLEAN | no | `false` | |
| `review_reasons` | JSONB | no | `'[]'` | `[{code, params}]`; the panel renders the sentence. Empty list = no review needed. |
| `rubric_version` | VARCHAR(16) | no | | `"v1"` in phase 1. Stored per score so a rubric change never silently re-bases yesterday's numbers. |
| `provider`, `model` | VARCHAR(32/64) | no | | |
| `llm_calls` | SMALLINT | no | `1` | Includes the invalid-response retries (`analysis.invalid_retries`). |
| `prompt_tokens`, `completion_tokens` | INTEGER | yes | | As reported by the provider; null when it reports nothing. The LLM billing unit (§11.1). |
| `cost_micro_usd` | BIGINT | yes | | Measured units × the admin-entered price. Null while the price is unset — **null means "not priced", never "free"**. |
| `scored_at` | TIMESTAMPTZ | no | | |

Indexes: unique on `call_id`; `ix_call_scores_overall` on `overall_score`;
`ix_call_scores_review` on `scored_at DESC` partial `WHERE needs_review`;
`ix_call_scores_time` on `scored_at DESC`.

#### `call_analysis_state` — one row per call the pipeline has touched

Singular mass noun, following the existing `device_health`.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `call_id` | UUID | no | | FK `calls.id` CASCADE, **UNIQUE** |
| `stage` | `analysis_stage` | no | `'queued'` | |
| `attempts` | SMALLINT | no | `0` | |
| `asr_calls`, `llm_calls` | SMALLINT | no | `0` | Calls that actually reached a provider, i.e. that cost money. A re-run must not increase these, and a test asserts it. |
| `queued_at` | TIMESTAMPTZ | no | `now()` | Claim order. |
| `last_run_at` | TIMESTAMPTZ | yes | | Stale detection reads it. |
| `transcribed_at`, `scored_at` | TIMESTAMPTZ | yes | | |
| `failure_code` | `analysis_failure` | yes | | |
| `failure_stage` | VARCHAR(16) | yes | | `transcribe` \| `score`. |
| `failure_detail` | TEXT | yes | | The provider's own message, passed through `errors.redact()`. English or the vendor's language; the Uzbek headline comes from `failure_code`. |
| `duration_ms` | INTEGER | yes | | End-to-end for the run. |
| `cost_micro_usd` | BIGINT | no | `0` | The run's measured cost; `0` also means "not priced". |

Constraint — the house idiom, copied from `calls.audio_reason_present`:

```
CHECK ( (stage IN ('failed','skipped')) = (failure_code IS NOT NULL) )
```

so "a stopped call always carries a reason" is a database fact, not a habit.
Indexes: unique on `call_id`; `ix_analysis_state_claim` on `(stage, queued_at)`
— the claim query's index; `ix_analysis_state_failure` on `failure_code` partial
`WHERE stage = 'failed'`.

#### `ai_provider_cooldowns` — at most two rows, ever

No `UUIDMixin`: the role is the identity, exactly as `app_settings` uses its key.

| Column | Type | Null | Notes |
|---|---|---|---|
| `role` | `ai_role` | no | **Primary key.** Per role, not per provider: one account can serve both roles against different models and different quotas, and an exhausted ASR quota must not stop scoring. |
| `until_at` | TIMESTAMPTZ | no | Past it, the road is open. |
| `started_at` | TIMESTAMPTZ | no | |
| `reason_code` | `analysis_failure` | no | |
| `detail` | TEXT | yes | Redacted. |

The extension rule from `ProviderCooldown.start()` is preserved and matters: a
**longer** existing cooldown is never shortened, because two workers hitting 429
seconds apart would otherwise let the second one's short window cancel the
first's daily one.

### 2.3 Timezone, rounding, deletion

- Every timestamp is stored UTC-aware and rendered in `Asia/Tashkent`
  (`core/clock.TASHKENT`, `CONVENTIONS.md` §6). The monthly cost window is a
  **Tashkent** calendar month, because the person reading the bill lives there.
- **Rounding:** scores round half **up**, via `validator._round_half_up`, never
  Python's `round()` (banker's rounding turns 12.5 into 12). The rubric resolves
  doubt in the employee's favour and the arithmetic must point the same way.
- **Currency:** integer micro-USD (1 USD = 1,000,000). There is no `Decimal` and
  no float anywhere near money.
- **Soft delete:** none of these tables has one. Analysis output is derived data:
  it is recomputed, not archived. `ON DELETE CASCADE` on `call_id` is
  theoretical — `calls` answers 405 to `DELETE` for every role (`api/panel/calls.py`)
  — but it is the correct declaration and costs nothing.
- **Retention:** transcripts and scores are **not** deleted by
  `audio_retention`. When the audio expires at twelve months the transcript is
  what remains, and it is a hundredth of the size. Stated explicitly because the
  opposite is a plausible reading of UC-26.

### 2.4 Stage and failure semantics

| Situation | `stage` | `failure_code` |
|---|---|---|
| Eligible, waiting | `queued` | null |
| In flight | `transcribing` / `scoring` | null |
| Transcribed and scored | `completed` | null |
| Transcribed, deliberately not scored (internal call) | `skipped` | `call_type_internal` |
| Not analysable at all | `skipped` | `no_audio` / `audio_expired` / `call_too_short` / `call_type_unknown` |
| Stopped by something that will pass | `failed` | a transient code |
| Stopped by something that will not | `failed` | a permanent code |

`skipped` is not a failure, and the panel must not paint it as one. That
distinction is the reason BonviZvonki grew `SKIPPED` in the first place.

### 2.5 The rubric is code in phase 1

`rubric_default.DEFAULT_RUBRIC` is the rubric; `RUBRIC_VERSION = "v1"` is stamped
on every score. Changing it needs a deploy, and the version string must be bumped
in the same change — a modified rubric under an unchanged version makes two
scores incomparable while claiming they are comparable. Phase 2 ports
`rubric_models.py` + `rubric_service.py` verbatim and reads the active row
instead; every phase-1 score already carries `"v1"`, so nothing needs
back-filling.

### 2.6 Which calls are analysed

The gate, evaluated in the dispatch job and re-checked before work starts:

```
disposition = 'answered'                     -- unanswered calls have no conversation
AND has_audio = true                          -- and the recording is not deleted
AND duration_sec >= analysis.min_duration_sec  -- default 30
AND call_type = 'external'                    -- see below
```

- `call_type = 'internal'` → transcript and score both skipped,
  `call_type_internal`. BonviZvonki transcribed internal calls anyway, for
  search and for disputes. **Phase 1 does not**, because phase 1 has no search
  page: it would be paying an ASR bill for a feature that does not exist.
  Reversible with one settings key, `analysis.transcribe_internal`, default
  `false`.
- `call_type = 'unknown'` → skipped, `call_type_unknown`. `unknown` is what
  BonviCall returns when the line directory is empty
  (`modules/calls/rules.py::classify_call_type`, and the comment there records
  that BonviZvonki's opposite default mislabelled 82 of 98 calls). Scoring
  those would score colleagues against a sales rubric — money spent to lower an
  employee's average unfairly. The status endpoint surfaces the count, so "412
  calls are waiting on the line directory" is visible rather than silent, and
  dispatch statement (b) (§5) puts them back in the queue by itself once an
  admin fills the directory and `reclassify_calls` restamps them. **These two
  reasons, and only these two, are re-checkable** — the rest are facts about the
  call that will not change.
- A call whose audio retention has removed the blob → `audio_expired`.
- `duration_sec` and `disposition` are already tied together by a CHECK on
  `calls` (`answered_has_duration`), so the duration rule cannot accidentally
  admit an unanswered call.

---

## 3. Audio: the file is ours, and that deletes code

BonviZvonki never owns the bytes. Its contract's first rule is that audio is
stored neither on disk nor in the database: `pipeline/application/deps.py`
opens a MoiZvonki HTTP stream, `transcribe.py` pipes it straight into the ASR
client through a counting generator, and
`ai/infrastructure/providers/base.py::collect_audio` buffers it in memory behind
a 200 MB cap. Three separate pieces of code exist only to honour that rule.

BonviCall owns the file. It is on local disk under `/data/audio`, written by
`modules/audio/service.py` and reachable only through
`core/storage.py::LocalFsAudioStorage` — and `CONVENTIONS.md` §2/SPEC §6 state
that **no module outside `modules/audio/` may open an audio file by path.**

### 3.1 The seam

One additive method on the existing `AudioService`, and nothing else:

```python
# server/src/modules/audio/service.py  — ADDITIVE: one dataclass, one method.
# No existing line is edited.

@dataclass(frozen=True)
class AnalysisSource:
    """Enough for an ASR client, and no path in it.

    ``open`` is bound by AudioService over the storage seam, so the caller can
    read the bytes without ever holding a storage key. Same idiom as the
    existing ``archive_for()``, which binds ``open_bytes`` per entry.
    """
    call_id: uuid.UUID
    bytes: int
    duration_ms: int | None
    content_type: str                 # audio/ogg | audio/mp4
    filename: str                     # call-<call_id>.ogg | .m4a
    open: Callable[[], IO[bytes]]

async def analysis_source(self, call_id: uuid.UUID) -> AnalysisSource: ...
```

- `analysis_source` resolves `CallAudioModel` by `call_id` and raises
  `NotFoundError(ErrorCode.AUDIO_NOT_FOUND)` when there is no row and
  `GoneError(ErrorCode.AUDIO_EXPIRED)` when `deleted_at` is set — the same two
  answers `_source_for()` already gives the panel, so the rules cannot diverge.
- `open` is `lambda key=audio.storage_key: self.storage.open_range(key, 0, None)`.
  **The key stays inside the closure and inside `modules/audio/`**; the analysis
  module receives a callable, never a path, never a key. No new file-opening
  code is written anywhere in the product.
- `filename` is built from `call_audio.container`: `ogg` → `.ogg`, `mp4` → `.m4a`.
  It exists because the provider SDKs infer the MIME type from the name
  (`providers/base.guess_mime`).
- **No `Principal`.** This is called from a worker job, not a request. Row-level
  scope does not apply and inventing a principal for it would be a lie.
- The pipeline wraps the handle in an `AsyncIterator[bytes]` — a 5-line helper in
  `transcribe.py` that reads `core.storage.CHUNK_BYTES` at a time inside
  `asyncio.to_thread`, because a synchronous file read on the event loop blocks
  every other call in flight. The
  `ASRClient.transcribe(audio: AsyncIterator[bytes], *, filename, language)`
  signature is therefore **unchanged** and all three provider clients copy as-is.
- Size is checked before the first read: `source.bytes` against
  `providers/base.MAX_AUDIO_MB`. Over it, the call is `failed` /
  `audio_too_large` and nothing is allocated.

### 3.2 What this deletes from the ported code

| Deleted | Lines | Because |
|---|---|---|
| `pipeline/application/deps.py::default_open_recording` and the `moizvonki` import chain | ≈14 | There is no MoiZvonki here. |
| `transcribe.py::_Counter` and `_counted()` | ≈12 | The byte count is `call_audio.bytes`, known before reading. Counting a stream to discover a number the database already holds is work for nothing. |
| `transcribe.py::_EXTENSION` (content-type → extension map) | ≈13 | `call_audio.container` is an enum: `ogg` → `.ogg`, `mp4` → `.m4a`. The map existed to guess at an HTTP header. |
| The **second** `await session.commit()` inside `attempt()` | 1 + 8 of comment | Its stated reason is that `open_recording` re-reads MoiZvonki credentials from the database on every retry. Nothing is read now. **The first commit — before the provider call — stays**, and so does its reason: settings reads open a transaction, and waiting out a 60-second retry inside one puts the worker in `idle in transaction`. |
| `base.collect_audio`'s cap as a *discovery* | 0 (logic kept, meaning changed) | The size is known up front, so oversized audio is refused before a byte is allocated. The in-loop cap stays as a second line of defence for a file that lies about its size. |
| The privacy framing of the whole file — "audio must never materialise", "no `open()`, no `tempfile`, no `BytesIO` in this file, ever" | ≈20 of comment | **This is the dangerous one.** Copied across, those comments read as a rule about BonviCall, and the next person obeys a constraint that does not exist while missing the one that does: the file may be opened, but **only by `modules/audio/`**. Replace the comment block; do not translate it. |

### 3.3 What it does *not* change

- Retries are now cheap. `with_backoff`'s argument that every retry re-downloads
  megabytes no longer applies — but its other two reasons do (a daily quota will
  not clear, and sleeping ten minutes inside a worker slot stalls the queue), so
  **the code stays and the comment is rewritten.** Copying the old comment
  verbatim would leave a false justification attached to correct code, which is
  worse than no comment.
- Analysis never deletes, moves or rewrites an audio file. `audio_retention`
  owns deletion (`modules/audio/jobs.py`), and it is not touched.
- Analysis never reads `/data/audio` by path, never constructs a storage key,
  and never imports `LocalFsAudioStorage`. `grep -rn "audio_storage_path\|LocalFsAudioStorage" server/src/modules/analysis/`
  must return nothing — that grep is the review check.

---

## 4. Providers, keys, dependencies, the flag and the cap

### 4.1 The registry stays, unchanged in shape

`registry.py` holds one `AIProvider` entry per vendor; adding a vendor is adding
an entry. `client_kind` selects the protocol, so any OpenAI-compatible vendor
(DeepSeek, Together, Fireworks, xAI, Mistral) needs a registry row and a
`base_url` and no code at all. Phase 1 ships the three that exist:

| Key | Roles | Default model | Why |
|---|---|---|---|
| `gemini` | ASR, LLM | `gemini-3.1-flash-lite` | **The only ASR tested on real Uzbek calls that works.** It takes audio directly, separates speakers, and emits the timestamps the prompt asks for. Its free tier allows 500 requests/day against the flash family's 20. |
| `anthropic` | LLM | `claude-haiku-4-5` | The intended scorer. Text only. |
| `openai` | ASR, LLM | `gpt-4o-transcribe` / `gpt-4.1-mini` | Present so a switch is a settings change. Uzbek ASR quality is mediocre — the registry comment says so. |

Defaults resolve to `gemini` for ASR and `anthropic` for LLM
(`default_provider_key`). Both are overridable per role in `app_settings`.

### 4.2 Keys live in the environment, not in `app_settings`

**This is the one place phase 1 deliberately departs from BonviZvonki**, which
stores each vendor key in a settings row (`ai.<vendor>_api_key`).

It cannot work here: `app_settings` is served by `GET /api/v1/settings` behind
`settings:read`, and `core/permissions.py` grants `settings:read` to **manager**
as well as admin. A key in that table is a key every manager can read. BonviCall
has already made this exact call once — `core/config.py` carries the comment
next to the MoiZvonki credentials: *"Credentials live in the environment and NOT
in `app_settings`: the API key is a secret, and `app_settings` is readable by
every panel admin and is rendered on a settings page."* Phase 1 follows the
precedent that is already in the file.

Add three `SecretStr` fields to `core/config.py::Settings`, and the matching
lines to `.env.example` in the same commit (that file's own rule):

```python
ai_gemini_api_key:    SecretStr = SecretStr("")   # AI_GEMINI_API_KEY
ai_openai_api_key:    SecretStr = SecretStr("")   # AI_OPENAI_API_KEY
ai_anthropic_api_key: SecretStr = SecretStr("")   # AI_ANTHROPIC_API_KEY
```

`AIProvider.env_var` is replaced by `settings_attr: str` — the **name of the
`Settings` field**, not the environment variable. `factory.resolve()` then does
`getattr(get_settings(), provider.settings_attr).get_secret_value()`. Reading
`os.environ` directly is forbidden here: `core/config.py` is the one place the
configuration surface is declared, and a key read around it would not appear in
`.env.example` and would not be found when the value comes from a Compose
`env_file`. A blank key raises the ported `missing_key()`, which the service
turns into `409 ai_not_configured`. `legacy_key_settings` is deleted.

**One trap worth naming:** the `openai` and `anthropic` SDKs fall back to their
own `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` environment variables when no key is
passed. `ClientConfig.api_key` is always passed explicitly, so that fallback is
never reached — but do not "simplify" by dropping the argument, or an unset
`AI_OPENAI_API_KEY` would silently start billing whatever ambient key the host
happens to carry.

### 4.3 Dependencies — and the pydantic bump that must go first

Add to `server/requirements.txt`:

```
# AI providers — official vendor SDKs, imported lazily inside the client so a
# missing package is a clear error at call time rather than a server that will
# not start (analysis/providers/builders.py).
google-genai==2.18.1
anthropic==0.122.0
openai==3.1.0
```

Versions are BonviZvonki's, which are the versions these clients were written
and measured against.

> **`google-genai==2.18.1` requires `pydantic>=2.12.5`. BonviCall pins
> `pydantic==2.10.4`.** BonviZvonki's own `requirements.txt` carries the warning
> and the resolution: it runs `pydantic==2.13.4` with `pydantic-settings==2.7.1`
> **and the same `fastapi==0.115.6` BonviCall runs**, which is direct evidence
> the combination works. Even so, a Pydantic minor bump on a live API is not a
> side effect of an AI feature. **Task 1 of §10 is the bump, alone, merged and
> deployed before any analysis code exists**, so that if it breaks anything it
> is one revert of one change.
>
> Fallback if the bump is refused or fails: drop `google-genai` and call the
> Gemini REST endpoint with `httpx` (already a dependency) — roughly 60 lines
> replacing `providers/gemini.py`'s SDK calls, keeping the prompt, the model
> filters and the error translation. That is the option to take **only** if the
> bump fails; it trades the copy-as-is property of the file for zero dependency
> risk.

No new dependency is needed for queueing or locking: `apscheduler` and
PostgreSQL advisory locks are already in place (§5).

### 4.4 The feature flag

`analysis.enabled`, boolean, **default `false`, seeded false by the migration.**

| Reader | Behaviour when false |
|---|---|
| `analysis_dispatch` job | returns 0 immediately; queues nothing |
| `analysis_run` job | returns 0 immediately; claims nothing |
| `POST /api/v1/analysis/calls/{id}` | `409 analysis_disabled` |
| `GET /api/v1/analysis/calls/{id}` | answers normally — rows already written stay readable |
| `GET /api/v1/analysis/status` | answers normally, with `enabled: false` |

Deploying phase 1 to production therefore changes the behaviour of the running
system in exactly one way: two tables and two job names exist and do nothing.
Turning it on is one settings row, and turning it off again is the same row —
which is the rollback, and it is why `analysis.enabled` is a setting and not an
environment variable.

### 4.5 The cost cap — two caps, because one of them can be zero

| Key | Default | Enforced |
|---|---|---|
| `analysis.monthly_cost_cap_micro_usd` | `50000000` ($50) | Before claiming each call: the Tashkent-month sum of `call_analysis_state.cost_micro_usd` ≥ cap → the run stops, an `analysis_cost_cap_reached` alert is raised once, and dispatch stops queueing. |
| `analysis.monthly_max_calls` | `3000` | The same check on a count of `call_analysis_state` rows with `stage = 'completed'` in the month. |

**Why both.** The money cap is computed from measured units × an admin-entered
price (§11.1), and the price defaults to zero because inventing a vendor price
in a specification is how a budget gets justified by a number nobody checked.
With the price unset, every call costs 0 and the money cap can never trip. The
call-count cap always means something, so it is the one that actually protects
the account on day one; the money cap becomes the real control the moment an
admin types the vendor's price in. Both are settings rows, both are visible on
`GET /analysis/status`, and the alert says which one stopped the pipeline.

### 4.6 Every settings key, with its seeded default

Declared as constants in `core/settings_keys.py`, seeded by migration 010, and
added to the expected dict in
`tests/test_schema.py::test_every_settings_key_is_seeded_with_its_documented_default`
— **that assertion is an exact equality, so a seeded row missing from it fails
the suite** (§10, task 3).

**Every value is an integer, a boolean or a string.** BonviZvonki holds four of
these as floats from the environment; here `value_type` is one of
`int | bool | string | list | time` and the panel renders the editor from it, so
the four become whole seconds. Their defaults were already whole numbers.

| Key | Type | Default | What it decides |
|---|---|---|---|
| `analysis.enabled` | bool | `false` | The feature flag (§4.4). |
| `analysis.asr_provider` | string | `"gemini"` | Registry key for the ASR role. |
| `analysis.asr_model` | string | `"gemini-3.1-flash-lite"` | Empty falls back to the registry default. |
| `analysis.asr_language` | string | `"uz"` | Passed to the provider. **Empty is legal and means "you detect it"** — deliberately allowed for a genuinely multilingual fleet. |
| `analysis.llm_provider` | string | `"anthropic"` | |
| `analysis.llm_model` | string | `"claude-haiku-4-5"` | |
| `analysis.min_duration_sec` | int | `30` | Below this, `call_too_short`. Read in **both** the dispatch gate and the pre-run check — BonviZvonki had two sources here (30 from env, 10 from settings) and the button reported "0 calls" while the setting looked applied. |
| `analysis.transcribe_internal` | bool | `false` | §2.6, Q2. |
| `analysis.lookback_hours` | int | `168` | How far back dispatch looks, on `calls.received_at`. **Seven days, not two:** audio arrives after the call row (R7) and a phone that was offline has up to `upload.session_ttl_days = 7` to deliver it. A 48-hour window would permanently miss every recording from a handset that spent a weekend out of coverage, and nothing would say so. |
| `analysis.max_calls_per_run` | int | `200` | Ceiling per dispatch tick. Protects against a backlog being swallowed whole. |
| `analysis.concurrency` | int | `2` | Calls in flight inside one `analysis_run`. |
| `analysis.asr_rpm` | int | `60` | Requests per minute; `0` disables the limiter. |
| `analysis.llm_rpm` | int | `120` | |
| `analysis.max_retries` | int | `4` | Transient retries per provider call. |
| `analysis.backoff_base_sec` | int | `2` | Doubles per attempt, plus jitter. |
| `analysis.backoff_max_sec` | int | `60` | Ceiling on one wait. |
| `analysis.max_wait_sec` | int | `60` | A vendor asking for longer stops the stage instead of sleeping — sleeping ten minutes inside a worker slot stalls the queue and reads from outside as a hung worker. |
| `analysis.quota_cooldown_sec` | int | `1800` | How long a role sits out after a **daily** quota. Half an hour, not "until tomorrow": an admin may raise the tier or swap a key, and the system should notice by itself. |
| `analysis.invalid_retries` | int | `2` | Re-asks when the model's arithmetic fails validation, with the error text appended. **2, not 1:** cheap models miscount block totals and usually fix it on the second ask; the alternative is a call with no score at all. |
| `analysis.call_timeout_sec` | int | `900` | End-to-end ceiling for one call. `analysis_stale_reset` uses twice this. |
| `analysis.retry_transient_days` | int | `7` | How far back the nightly retry reaches. |
| `analysis.monthly_cost_cap_micro_usd` | int | `50000000` | §4.5. |
| `analysis.monthly_max_calls` | int | `3000` | §4.5. |
| `analysis.price_asr_micro_usd_per_minute` | int | `0` | `0` = not priced (§11.1). |
| `analysis.price_llm_micro_usd_per_1k_input_tokens` | int | `0` | |
| `analysis.price_llm_micro_usd_per_1k_output_tokens` | int | `0` | |

Two of BonviZvonki's knobs are **not** settings: `lock_ttl_sec` has nothing to
lock any more (§5), and `progress_every` is a logging cadence rather than a
threshold and stays a module constant. None of these keys is added to
`DEVICE_VISIBLE_KEYS` — a handset has no business knowing any of it.

---

## 5. Scheduling: four jobs in the existing worker

No Celery. No Redis. No broker. `server/src/worker.py` already runs APScheduler
with fourteen jobs, each taking a PostgreSQL advisory lock
(`core/jobs.py::JobRunner`), each with `max_instances=1` and `coalesce=True`,
each alerting after three consecutive failures. A module exports a callable with
the signature `async def (AsyncSession) -> int`; `worker.py` decides when it
runs. That is the whole coupling, and it is one line of shared code per job.

| Job | Trigger | What it does |
|---|---|---|
| `analysis_dispatch` | `IntervalTrigger(minutes=5)` | Two statements, both pure SQL, no provider contact, and safe to run any number of times. **(a)** Calls matching §2.6 with `calls.received_at` inside `analysis.lookback_hours` and **no state row** → `INSERT … ON CONFLICT (call_id) DO NOTHING`, at most `analysis.max_calls_per_run` per tick, ordered by `received_at`. **(b)** Rows already `skipped` whose reason is in `RECHECKABLE_SKIPS = {call_type_unknown, call_type_internal}` **and whose call no longer matches that reason** → back to `queued`. Statement (b) is what makes §2.6's self-healing real: a `skipped` row is not invisible to dispatch, and once an admin fills the line directory and `reclassify_calls` restamps `call_type`, those calls re-enter the queue by themselves. Without it, every call analysed before the directory existed would stay skipped forever. Returns nothing and queues nothing when `analysis.enabled` is false or either monthly cap is reached. |
| `analysis_run` | `IntervalTrigger(minutes=2)` | Claims up to `analysis.concurrency × 4` queued rows and processes them. **The only job that spends money.** |
| `analysis_retry_transient` | `CronTrigger(hour=1, minute=45, tz=TASHKENT)` | Re-queues rows whose `stage='failed'` and whose `failure_code` is in `TRANSIENT_FAILURES`, within `analysis.retry_transient_days` (default 7), oldest `last_run_at` first. This is BonviZvonki's hardest-won lesson: a 48-hour window left 885 rate-limited calls permanently failed, because the quota reset the next day but nothing ever looked at them again. Runs at 01:45, between `model_capture_stats` (01:00) and `audio_retention` (02:00), so a slow retry cannot delay the job that deletes data. |
| `analysis_stale_reset` | `IntervalTrigger(hours=1)` | Rows stuck in `transcribing`/`scoring` with `last_run_at` older than `2 × analysis.call_timeout_sec` become `failed` / `interrupted`. The pipeline commits at every stage boundary on purpose, which means a killed worker leaves a visible half-finished row rather than an invisible rollback. This closes them; the next dispatch picks them up. `last_run_at IS NULL` is left alone — that row never ran. |

**Locking, in full, because the Redis version is what is being replaced.**

1. Between workers: `JobRunner` takes `pg_try_advisory_lock(lock_key("analysis_run"))`
   and **skips** if another process holds it. Only one `analysis_run` executes
   anywhere at a time.
2. Between a job and itself: `max_instances=1` and `coalesce=True` — a late tick
   is dropped, not queued behind the running one.
3. Between rows, and against a hand-run `make job n=analysis_run`: the claim is
   `SELECT … WHERE stage='queued' ORDER BY queued_at FOR UPDATE SKIP LOCKED LIMIT n`,
   followed by an `UPDATE … SET stage='transcribing'` and a commit before any
   provider call. Two claimers can never take the same row, so BonviZvonki's
   `CallLock` (and the doubled ASR bill it prevented) is unnecessary.

Because (1) holds, the rate limiter does not need to be shared across processes,
which is what made it Redis-backed there. An in-process sliding window inside one
`analysis_run` is exact rather than approximate.

Two more shared-file edits in `worker.py`: the four entries in `SCHEDULE`, and
`alert_on_repeated_failure` learning that a job whose name starts with
`analysis_` raises `AlertKind.ANALYSIS_JOB_FAILED` rather than falling through to
`RETENTION_JOB_FAILED`. Without that line, a stalled AI pipeline raises an alert
that says retention failed, and somebody goes looking at the wrong subsystem at
the worst possible moment.

`tests/test_jobs.py::test_every_job_spec_names_is_registered` asserts a set of
names is a subset of `SCHEDULE`; add the four.

---

## 6. RBAC and the API

### 6.1 Permissions — `server/src/core/permissions.py`

Two constants. Both parts must be lower-case **alphabetic only** — no digits, no
underscores — because `tests/test_permissions.py::test_permission_names_follow_the_convention`
asserts `part.islower() and part.isalpha()` on every segment.

```python
ANALYSIS_READ = "analysis:read"
ANALYSIS_RUN  = "analysis:run"
```

| Role | `analysis:read` | `analysis:run` | Reasoning |
|---|---|---|---|
| `admin` | yes | yes | |
| `manager` | yes | **no** | A manager reviews calls; pressing this button spends money. Same line the registry already draws at `settings:write` and `installations:revoke`. |
| `sales` | **no** | no | See §12 Q1. Not an oversight — a decision, with a comment in the registry saying so, as `CONVENTIONS.md` §11 requires for a permission deliberately withheld. |
| `service` | no | no | The export contract (SPEC §4.9) is frozen and additive-only; analysis is not in it. |

`tests/test_permissions.py::EXPECTED_MATRIX` is a transcription of the matrix and
must be updated in the same change, or the suite fails — that is the file doing
its job. `panel/src/shared/auth/permissions.ts` mirrors the constants for the
panel's gates and needs the same two lines.

### 6.2 Endpoints — `server/src/api/panel/analysis.py`

`APIRouter(prefix="/analysis", tags=["Analysis"])`, included from
`api/panel/__init__.py`. Three endpoints; the surface is deliberately smaller
than BonviZvonki's four.

**The path is `/analysis/calls/{call_id}` and not `/calls/{call_id}/analysis`**
so that the whole server surface lands in new files. Adding a route to
`api/panel/calls.py` would mean editing a router that serves the product's
busiest page, for a cosmetic gain.

#### `GET /api/v1/analysis/calls/{call_id}` — `analysis:read`

```jsonc
// 200
{
  "call_id": "…",
  // The flag, repeated here on purpose: the call detail page must decide what
  // to render from ONE request. Making every page load also hit
  // /analysis/status to learn whether the feature exists would be two round
  // trips for a boolean.
  "enabled": true,
  "state": {
    "stage": "completed",
    "attempts": 1,
    "queued_at": "…", "last_run_at": "…", "transcribed_at": "…", "scored_at": "…",
    "failure_code": null, "failure_stage": null, "failure_detail": null,
    "asr_calls": 1, "llm_calls": 1, "cost_micro_usd": 0
  },
  "transcript": {
    "text": "[00:00] SPEAKER_0: …",
    "language": "uz", "provider": "gemini", "model": "gemini-3.1-flash-lite",
    "word_count": 412, "audio_duration_ms": 184000, "transcribed_at": "…"
  },
  "score": {
    "overall_score": 78, "blocks": {"script": 20, "communication": 18, …},
    "block_details": { … }, "red_flags": [ … ], "outcome_signal": { … },
    "sentiment": "positive", "transcript_quality": "high",
    "coaching_note": "…", "confidence_pct": 84,
    "needs_review": false, "review_reasons": [],
    "rubric_version": "v1", "model": "claude-haiku-4-5", "scored_at": "…"
  }
}
```

- `state`, `transcript` and `score` are each independently nullable. A call the
  pipeline has never touched answers `200` with all three null — **not 404**.
  404 here would mean "no such call", and the panel section must be able to
  distinguish "not analysed" from "call does not exist".
- Visibility is decided by `CallService.get(principal, call_id)`, so a call
  belonging to another agent is a **404** exactly as everywhere else. The
  analysis service does not re-implement scope.

#### `POST /api/v1/analysis/calls/{call_id}` — `analysis:run`

Body: `{"force": false}`. Queues one call now; the worker picks it up within two
minutes. **Never runs a provider call inside the request** — an LLM round trip
behind an HTTP request is how a panel times out and a user presses the button
again.

Returns `200` with the same `state` object, always, whether the row was created
or already existed. Re-posting is indistinguishable from the first post
(`CONVENTIONS.md` §5's shape, applied to a panel write). `force: true`
additionally clears the existing transcript and score so they are recomputed —
and that is the only way to spend money twice on one call.

| Failure | Status | Code |
|---|---|---|
| `analysis.enabled` is false | 409 | `analysis_disabled` |
| Call fails the §2.6 gate | 409 | `call_not_analysable` (`detail` names which rule) |
| Monthly cap already reached | 409 | `analysis_cost_cap_reached` |
| No provider key configured | 409 | `ai_not_configured` |
| Call not visible to this principal | 404 | `not_found` |

#### `GET /api/v1/analysis/status` — `analysis:read`

```jsonc
{
  "enabled": false,
  "stages": {"queued": 12, "transcribing": 1, "scoring": 0,
             "completed": 431, "skipped": 88, "failed": 9},
  "waiting_retry": 7,
  "not_analysable": {"call_type_unknown": 412, "call_too_short": 51, "no_audio": 18},
  "cooldowns": {"asr": {"seconds_left": 1420, "reason_code": "provider_rate_limit"}},
  "month": {
    "from": "2026-09-01", "calls": 431,
    "audio_minutes": 1840, "prompt_tokens": 3120000, "completion_tokens": 410000,
    "cost_micro_usd": 0, "priced": false,
    "cap_micro_usd": 50000000, "cap_calls": 3000
  },
  "recent_failures": [{"call_id": "…", "started_at": "…", "stage": "transcribe",
                       "code": "provider_rate_limit", "detail": "…", "attempts": 3,
                       "last_run_at": "…"}]
}
```

`waiting_retry` is separate from `stages.failed` on purpose (§1.3, `queue.py`).
`priced: false` is what stops the panel rendering `$0.00` and implying the
feature is free (§11.1).

Pagination: none of the three is a list endpoint; `recent_failures` is capped at
20 server-side. The cursor conventions of SPEC §4.7 do not apply.

**Name the two response schemas `CallAnalysisResponse` and
`AnalysisStatusResponse`.** `tests/test_conformance.py::test_every_list_response_has_the_same_shape`
fires on any schema whose name ends in `ListResponse` or `ListOut` and demands
`items` + `total`. Neither of these is a list of rows, so the correct action is
to avoid the suffix — not to add an entry to that test's `NOT_A_LIST` set.

### 6.3 Error codes — `core/errors.py` and `core/messages_uz.py`

Four new `ErrorCode` constants, each with an Uzbek message
(`tests/test_errors.py::test_every_code_has_a_message` enforces the pairing):

| Code | Status | Meaning |
|---|---|---|
| `analysis_disabled` | 409 | The feature is off for this deployment. |
| `analysis_cost_cap_reached` | 409 | This month's cap has been reached. |
| `call_not_analysable` | 409 | The call has no audio, is too short, or is not an external answered call. |
| `ai_not_configured` | 409 | No API key, unknown provider, or a provider that does not support the role. |

Internal provider failures (`provider_rate_limit`, `provider_network`, …) are
**not** `ErrorCode`s. They never leave through an HTTP status — they are written
to `call_analysis_state.failure_code` and read back through `GET .../analysis`.
Mixing the two vocabularies would put nineteen codes into the wire contract to
describe things no request ever caused.

`contract/openapi-panel-v1.json` and `contract/error-codes.json` are regenerated
by `make contract`; CI diffs them (`tests/test_app.py::test_contract_documents_are_committed_and_current`).

---

## 7. Panel surface — the call detail page and nothing else

Per `CONVENTIONS-CLIENT.md` §1. New module `panel/src/modules/analysis/`:

```
panel/src/modules/analysis/
├── api.ts                    TanStack Query hooks only
├── CallAnalysisSection.tsx   the section
└── __tests__/CallAnalysisSection.test.tsx
```

`api.ts` opens with the module-mapping docstring §1 requires: the panel's
`analysis` module reads the server's `analysis` module one-to-one. Types come
from `panel/src/shared/api/types.gen.ts` via `make types` — **no hand-written
interface mirroring a response** (`CONVENTIONS.md` §1). Query key
`['analysis', 'call', callId]`; the mutation invalidates `['analysis']`.

`CallAnalysisSection` is rendered by `CallDetailPage.tsx` below the existing
audio section. It renders **only** the success branch; loading, empty and error
are `QueryBoundary`'s job, and `grep -rn "isLoading\|isPending" panel/src/modules/`
must stay empty (§2).

**The rows below are evaluated in order; the first match wins.** Written as a
precedence list because the first two overlap, and a reader who takes them as an
unordered set will make "feature off, never analysed" render a button that
answers 409.

| Server state | What the section shows |
|---|---|
| No permission | Nothing at all — `can(Perm.ANALYSIS_READ)` is false and the section is not mounted, so no request is issued. |
| `enabled` false **and** `state` is null | Nothing. A disabled feature does not advertise itself. |
| `enabled` false **and** rows exist | The rows, read-only. No button — the flag is off, so pressing it would 409. |
| No state row | "Tahlil qilinmagan" + the **Tahlil qilish** button, shown only with `analysis:run`. |
| `queued` / `transcribing` / `scoring` | The stage, in Uzbek, with a spinner. Polls every 10 s while in a running stage; stops polling otherwise. |
| `skipped` | One Uzbek sentence keyed off `failure_code`. No error styling — this is not a failure. |
| `failed` | The Uzbek headline from `failure_code`, the retry button (`analysis:run`), and `failure_detail` in a muted monospace line. |
| `completed` | The score block and the transcript block. |

The score block: overall out of 100, the four block bars using `blocks` (values
already normalised to the applicable criteria — never recompute them in the
panel), the red-flag chips, `coaching_note`, and a "Tekshirish kerak" badge with
the `review_reasons` sentences when `needs_review`. `block_details.meta.applicable_max`
is what lets the header read "68 / 75" honestly when criteria were not
applicable; use it rather than assuming 100.

The transcript block: the raw text in a scrollable pane, speakers visually
separated, collapsed by default beyond ~15 lines. **Click-to-seek is phase 2** —
the timestamps are stored for it, and wiring it now means touching `AudioPlayer.tsx`.

Uzbek strings: `panel/src/shared/i18n/uz.json`, one catalogue, keys namespaced
`analysis.*` (`CONVENTIONS.md` §12). The set needed: stage names (6), failure
headlines (19, one per `analysis_failure` value), review-reason sentences (4,
with `{}` params), block labels (4), red-flag labels (6), sentiment (3),
quality (3), plus buttons and section headings — roughly 55 keys. Colours come
from CSS tokens; no hex, and all three theme cases written out (§3).

Files touched outside the new module — each a one- or two-line edit, listed here
because they are shared and therefore sequential (§10):
`panel/src/modules/calls/CallDetailPage.tsx` (one import, one element),
`panel/src/shared/auth/permissions.ts` (two constants),
`panel/src/shared/i18n/uz.json`, `panel/src/shared/api/types.gen.ts` (generated).
**No route and no nav entry** — phase 1 adds no page, so
`panel/src/app/router.tsx` and `AppShell.tsx` are untouched.

---

## 8. Deliberately not ported

| From BonviZvonki | Why not |
|---|---|
| `modules/auth`, `modules/users` | BonviCall has both, in production, with refresh-token rotation, an installation-bound device token and a role registry the panel already gates on. Replacing them would be a rewrite of the running system's front door for no gain. |
| `modules/settings` (its `SETTINGS_REGISTRY`, secret-value handling, settings endpoints) | BonviCall's `app_settings` + `core/settings_keys.py` + `SettingsService` already exist and are seeded by a migration and checked by a test. The one thing their system does that ours does not — hold secrets — is precisely the thing §4.2 refuses to do. |
| `modules/moizvonki` (client, ingest, contact sync, audio proxy) | BonviCall has its own ingestion: the device API for the fleet, plus `api/telephony/webhook.py` for cloud-telephony calls. Their audio proxy exists because they may not store audio; we do store it (§3). |
| `bootstrap.py` + `COLUMN_PATCHES` (`create_all` plus a list of `ALTER TABLE … IF NOT EXISTS` strings) | `CONVENTIONS.md` §10 rejects it by name, with the reasoning. BonviCall has nine real Alembic revisions and CI runs `alembic upgrade head` on every test run. `grep -rn "create_all" server/src` returns exactly one hit and must keep returning one. |
| Tests against the live development database (`MARK = "pytest-fixture"` + a `pytest_sessionfinish` sweeper) | The convention that caused a documented incident — sales tests wrote `client_contacts`, the sweeper did not know that table, and test contacts appeared on the real Contacts page. BonviCall uses a separate `bonvicall_test` database (`CONVENTIONS.md` §13). |
| **Celery + Redis** (`worker.py`, `tasks.py`, `runner.py`, `queue.enqueue_calls`, `broker_depth`, `worker_snapshot`, `limits.get_redis`, `CallLock`) | Two new infrastructure services, a broker to monitor and a second failure mode, to schedule four jobs. `worker.py` + `core/jobs.py` + PostgreSQL advisory locks + `FOR UPDATE SKIP LOCKED` do the same work with no new moving parts (§5). This is the single largest deletion in the port, ≈200 code lines. |
| Their frontend shell (`web/src/*` — React 19, their auth, layout, i18n with `fallbackLng`, hand-written response interfaces) | BonviCall's panel exists, uses generated types and has `QueryBoundary`. Their `isLoading` appears 67 times across 33 files, which `CONVENTIONS-CLIENT.md` §2 rejects by name. Only `modules/calls/audio.ts` was ever adopted from that codebase, and that was done in release 1. |
| `modules/sales`, `modules/surveys`, `modules/analytics`, `modules/clients`, `modules/groups`, `modules/agents` | Phases 2 and 3 (§0). |
| Scoring's rubric CRUD (`rubric_service.py`, `rubric_upgrade.py`, `rubric_models.py`, `scoring/presentation/router.py`) | Phase 2 (§2.5). Port them verbatim then — the single-active-rubric partial unique index in particular is a fix somebody already paid for. |
| `ai/application/catalog.py`, `ai/application/tester.py` | They exist to serve a settings UI phase 1 does not build (§1.2). |
| `score_writer.agent_client_rating` and review rule 5 | Reads the surveys tables. Phase 3. |

---

## 9. Tests

`CONVENTIONS.md` §13 governs: separate `bonvicall_test` database, `db` session
rolled back per test, **test data only through a factory**, expected values
computed in the test, `asyncio_mode = strict`, and no `assert True` and no
weakened assertion, ever.

### 9.1 Worth porting — ≈3,370 of their 5,225 test lines

| Their test | Lines | Port? | Note |
|---|---|---|---|
| `scoring/tests/test_applicability.py` | 477 | **yes, as-is** | The `na` rules. The most valuable test file in the three modules: it pins the behaviour that stopped the model marking seven criteria inapplicable in a ten-minute call and handing out 100s. Pure. |
| `scoring/tests/test_score_arithmetic.py` | 310 | **yes, as-is** | Criterion → block → overall, penalties, the zeroing red flag, half-up rounding. Pure. |
| `scoring/tests/test_response_parsing.py` | 180 | **yes, as-is** | Fenced JSON, prose before the object, non-object bodies. Pure. |
| `scoring/tests/test_validator.py` | 160 | **yes, as-is** | Invented block/criterion/flag keys are rejected. Pure. |
| `scoring/tests/test_known_defects.py` | 128 | **yes, as-is** | Regression cases from real model answers. Every one of these is a bug that reached a score once. |
| `scoring/tests/test_review_rules.py` | 69 | **yes, adapted** | Assert on `code` + `params` instead of the Uzbek sentence; drop the client-gap cases. |
| `ai/tests/test_provider_requests.py` | 307 | **yes, adapted** | Per-provider request shape through `httpx.MockTransport` — proves what we send without a vendor key or a bill. |
| `ai/tests/test_registry_and_factory.py` | 176 | **yes, adapted** | `check_registry()`, role support, default resolution. Adapt the key source to env (§4.2). |
| `ai/tests/conftest.py` | 17 | yes | Transport fixtures. |
| `pipeline/tests/stubs.py` | 276 | **yes, adapted** | Fake ASR/LLM plus a fake audio source. This file is what makes every pipeline test run without a network. |
| `pipeline/tests/test_retry_policy.py` | 179 | **yes, as-is** | Retryable vs not, vendor-stated delay beats exponential, no retry on a daily quota. Pure. |
| `pipeline/tests/test_idempotency.py` | 182 | **yes, adapted** | A second run makes no provider call and creates no second row. Rewire to house factories. |
| `pipeline/tests/test_select_calls.py` | 148 | **yes, adapted** | The eligibility gate — rewritten for §2.6's rules. |
| `pipeline/tests/test_stale_reset.py` | 148 | **yes, adapted** | |
| `pipeline/tests/test_transient_retry.py` | 147 | **yes, adapted** | Transient failures are re-queued; permanent ones are not. |
| `pipeline/tests/test_config.py` | 151 | **half** | Env parsing dies; the per-field defaults and bounds survive against `app_settings`. |
| `pipeline/tests/test_rate_limit.py` | 320 | **half (≈150)** | Redis-window cases die; window arithmetic, cooldown extension and the "longer cooldown is never shortened" rule survive against the table. |
| `pipeline/tests/test_queue_snapshot.py` | 232 | **half (≈120)** | Celery inspection dies; the DB snapshot and the failed-vs-waiting split survive. |
| `pipeline/tests/test_call_type_gate.py` | 388 | **≈120, rewritten** | Their sales/internal gate becomes BonviCall's external/internal/unknown gate. The *shape* of the tests transfers; the cases do not. |
| `scoring/tests/test_extra_rules.py` · `test_rubric_service.py` | 484 | no | Phase 2. |
| `ai/tests/test_settings_endpoint.py` | 238 | no | Their settings API. |
| `pipeline/tests/test_runner_loop.py` · `test_nightly.py` · `test_status_api.py` | 508 | no | Celery loop, MoiZvonki sync, their router. |

### 9.2 What this repo requires on top — ≈600 new lines

- **RBAC on all three endpoints** through T20's harness shape: 401 with no
  token, 403 for the wrong role (`manager` on `POST`, `sales` on everything),
  404 for another agent's call. Mandatory for any new endpoint
  (`CONVENTIONS.md` §13 and the global rules).
- **Three new factories in `server/conftest.py`** — `transcript_factory`,
  `score_factory`, `analysis_state_factory` — because test data is created only
  through a factory and twenty modules must not invent twenty definitions of "a
  score". `conftest.py` is a shared file and the factories are built in task 3,
  before anything needs them (§10).
- **`test_analysis_purity.py`**: `prompt.py`, `validator.py` and
  `rubric_default.py` import nothing from `src`, `sqlalchemy` or `fastapi`. The
  existing `tests/test_layering.py::test_rules_modules_are_pure` only globs
  `*/rules.py`, so these three need their own assertion or the property is
  unchecked.
- **Job idempotency**, one test per job — running it twice changes nothing and
  makes no second provider call. `core/jobs.py`'s contract: the lock stops two
  workers overlapping, it does not stop a restart.
- **Migration**: `make migrate-head-check` (a clean database reaches head) plus
  the enum-table equality test of §2.1. Model changes require `test-migration`
  by the global rules.
- **Panel (Vitest)**: all three `QueryBoundary` states render; the section is
  absent without `analysis:read`; the button is absent without `analysis:run`.
- **One manual smoke test**, `@pytest.mark.manual`, skipped by default, that
  calls `ping()` on the configured ASR and LLM clients with real keys. It is the
  only test in the suite that may cost money, and it never runs in CI.

---

## 10. Build order

Twelve tasks. Each is one agent's work. Hours are for an agent with this
document open, not for someone discovering the codebase.

| # | Task | Depends on | Parallel? | Hours |
|---|---|---|---|---|
| 1 | **Pydantic bump, alone** | — | No — merged and deployed by itself | 2 |
| 2 | **Shared registries** | 1 | **No** — six shared files | 3 |
| 3 | **Models + migration 010 + test factories** | 2 | **No** — single Alembic head | 5 |
| 4 | **Providers subpackage** | 2 | Yes | 5 |
| 5 | **Pure scoring core** | 2 | Yes | 5 |
| 6 | **Audio seam** | 2 | Yes | 2 |
| 7 | **Pipeline** | 3, 4, 5, 6 | No | 8 |
| 8 | **Worker registration** | 7 | No — shared file | 2 |
| 9 | **Panel API + contract** | 7 | No — shared files | 3 |
| 10 | **Server tests** | 8, 9 | Yes (with 11) | 4 |
| 11 | **Panel surface** | 9 | Yes (with 10) | 4 |
| 12 | **Rollout and measurement** | 10, 11 | No | 3 |

**Total ≈ 46 hours.** Critical path: 1 → 2 → 3 → 7 → 9 → 11 → 12 ≈ 28 hours.
Tasks 4, 5 and 6 run in parallel after task 2; 10 and 11 in parallel after 9.

**The three test factories belong to task 3, not task 10**, even though the
tests that need most of them come later: they depend only on `models.py`, they
live in the shared `server/conftest.py`, and tasks 7 and 10 both need them. A
factory written twice is how twenty modules end up with twenty definitions of
"a score" (`CONVENTIONS.md` §13).

### Shared files — sequential, never parallel

Following SPEC §11.2's list, these are the files two agents must never hold at
once. Each is owned by exactly one task above.

| File | Owner |
|---|---|
| `server/requirements.txt` | 1, then 4 |
| `server/src/core/enums.py` (5 enums + 2 `AlertKind` values + `PG_ENUM_TYPES`) | 2 |
| `server/src/core/settings_keys.py` | 2 |
| `server/src/core/errors.py` + `core/messages_uz.py` | 2 |
| `server/src/core/permissions.py` + `tests/test_permissions.py::EXPECTED_MATRIX` | 2 |
| `server/src/core/config.py` + `.env.example` | 2 |
| `server/tests/test_model_registry.py` (the enum parser fix, §2.1) | 2 |
| `server/src/core/models.py` (one import line) | 3 |
| `server/migrations/versions/010_create_analysis_schema.py` (the Alembic head) | 3 |
| `server/tests/test_schema.py` — the seeded-settings dict (**exact equality**, §4.6) | 3 |
| `server/src/modules/audio/service.py` (additive method) | 6 |
| `server/src/worker.py` (`SCHEDULE` + the alert mapping) + `tests/test_jobs.py` | 8 |
| `server/src/api/panel/__init__.py` | 9 |
| `contract/openapi-panel-v1.json`, `contract/error-codes.json` | 9 |
| `server/conftest.py` (three factories) | 3 |
| `panel/src/shared/auth/permissions.ts`, `shared/i18n/uz.json`, `modules/calls/CallDetailPage.tsx`, `shared/api/types.gen.ts` | 11 |

### Task detail and Definition of Done

**1 — Pydantic bump (2 h).** `pydantic 2.10.4 → 2.13.4`,
`pydantic-settings 2.7.0 → 2.7.1`. Nothing else.
*DoD:* `pip install -r server/requirements.txt` resolves; `pytest` fully green;
`make contract && git diff --exit-code contract/` clean — a serialisation change
would show up there and nowhere else; the panel builds; deployed and the running
system observed for one day before task 2 merges.

**2 — Shared registries (3 h).** Everything in the shared table above except the
migration and models. No behaviour, only declarations.
*DoD:* `pytest server/tests` green, including `test_permissions`,
`test_errors::test_every_code_has_a_message`, and the amended
`test_model_registry::test_migration_enum_table_matches_core_enums`;
`make lint` clean; `docs/ASSUMPTIONS.md` carries the module-set amendment
(§1.1) and the §14 language exception (§1.6).

**3 — Models, migration and factories (5 h).** `modules/analysis/models.py`
(four tables, §2.2), the three `server/conftest.py` factories
(`transcript_factory`, `score_factory`, `analysis_state_factory`), each with a
test in `tests/test_fixtures.py` proving it satisfies the CHECK constraints —
the shape `test_call_factory_satisfies_the_check_constraints` already sets. Then
the `core/models.py` registry line and migration `010` creating five enum
types + four tables + two `ALTER TYPE … ADD VALUE` + the twenty-six seeded
settings rows of §4.6, with its own literal `PG_ENUMS` block. `ALTER TYPE … ADD
VALUE` must sit inside `op.get_context().autocommit_block()` — migration `008`
is the working template.
*DoD:* `make migrate-head-check` passes on a scratch database; `alembic check`
produces an empty diff; the migration was **read** and contains no `op.drop_` in
`upgrade` (`test_the_migration_has_no_drop_in_upgrade`);
`test_every_column_documents_itself`, `test_no_float_column_anywhere`,
`test_every_datetime_column_is_timezone_aware`,
`test_model_registry_complete` and
`test_every_settings_key_is_seeded_with_its_documented_default` all pass — the
last one compares the whole table with `==`, so all twenty-six keys and their
exact seeded values go into its dict in this task, not later.

**4 — Providers (5 h).** `providers/*`, `registry.py`, `factory.py`,
`errors.py`, the three SDK pins. Ports §1.2.
*DoD:* `check_registry()` returns an empty list; `factory.resolve_from_values`
unit-tests pass with no database; the ported `test_provider_requests.py` passes
against `MockTransport` with no key present; importing the module with no SDK
installed does not raise (lazy import); `errors.redact()` has a test proving an
API key never reaches a log line (N26).

**5 — Pure scoring core (5 h).** `prompt.py`, `validator.py`,
`rubric_default.py`, `scorer.py`, `rules.py`, `entities.py`, plus the six ported
pure test files.
*DoD:* the five ported scoring test files pass unchanged in substance;
`test_analysis_purity.py` passes; `BLOCK_MAX` is derived from the rubric and the
rubric's blocks total exactly 100 (assert it — their `RubricService._validate`
enforced it and that check is not being ported).

**6 — Audio seam (2 h).** The two additive methods on `AudioService` (§3.1) and
their tests.
*DoD:* no existing line of `modules/audio/service.py` changed — the diff is
additive only; a test each for present, missing and retention-deleted audio
(404 / 410); the full existing audio test suite still green.

**7 — Pipeline (8 h).** `pipeline.py`, `transcribe.py`, `score.py`, `limits.py`,
`config.py`, `score_writer.py`, `service.py`, `jobs.py`. The largest task and
the one where every §1.3 seam is either honoured or quietly lost.
*DoD:* an end-to-end test with stubbed providers and a factory-built call
produces a transcript row, a score row and `stage='completed'`; re-running makes
zero provider calls and changes no row; every §2.4 skip path has a test; the
claim query is `FOR UPDATE SKIP LOCKED` and a test proves two claimers never
take the same row; `grep -rn "redis\|celery" server/src/modules/analysis/`
returns nothing; `grep -rn "LocalFsAudioStorage\|audio_storage_path" server/src/modules/analysis/`
returns nothing.

**8 — Worker (2 h).** Four `SCHEDULE` entries, the `alert_on_repeated_failure`
mapping, `tests/test_jobs.py`.
*DoD:* `make job n=analysis_dispatch` runs and returns 0 with the flag off;
`test_every_job_spec_names_is_registered` covers the four; each job has an
idempotency test; a job failing three times raises `analysis_job_failed` and not
`retention_job_failed`.

**9 — Panel API (3 h).** `api/panel/analysis.py`, `schemas.py`, the
`__init__.py` include, `make contract`.
*DoD:* three endpoints answer; `test_app.py::test_every_registered_route_is_protected_or_declared_public`
passes with no new `PUBLIC_ROUTES` entry; `test_every_router_module_is_registered`
passes; `make contract && git diff --exit-code contract/` is clean;
`test_conformance` passes; no `select(`, no `.commit()`, no `if user.role ==`
anywhere in the router (`test_layering`).

**10 — Server tests (4 h).** The RBAC file and the remaining ported pipeline
tests (the factories landed in task 3).
*DoD:* every endpoint has 401/403/404; `pytest` green; coverage of each
`analysis_failure` value that the code can actually produce; no `assert True`,
no `@pytest.mark.skip` without a task id.

**11 — Panel (4 h).** The module, the `CallDetailPage` insertion, `uz.json`,
`make types`, Vitest.
*DoD:* `npm run build` passes; `grep -rn "isLoading\|isPending" panel/src/modules/`
empty; no `any`, no `@ts-ignore`, no hex colour, no hand-written response type;
all three `QueryBoundary` states have a test; a `manager` sees the section and
not the button; a `sales` user sees neither.

**12 — Rollout and measurement (3 h).**

**There is no staging environment.** `grep -rin staging docs/ docker-compose.prod.yml`
returns nothing, and the only real Uzbek call recordings that exist are in
production. Copying customer audio onto a developer machine to measure a cost is
not a trade this document will make. So the measurement runs **in production,
inside the caps that exist for exactly this**:

1. Deploy: the three `.env` keys on the host, `make prod-migrate` (**read the
   migration first** — global rule), `analysis.enabled` left `false`. The system
   is unchanged. This half is the build's to do.
2. **Stop and ask the client.** Money is about to be spent and customer
   conversations are about to leave the machine — two of the four cases in the
   global rules where an agent stops. Present: the twenty-call trial, the
   provider, and what leaves the server.
3. On approval: `analysis.monthly_max_calls = 20`, then `analysis.enabled = true`.
   Dispatch queues twenty calls, the cap stops it, and
   `analysis_cost_cap_reached` fires. That is the controlled trial, run by the
   product's own safety rails rather than by a person watching a log.
4. Record in `docs/ASSUMPTIONS.md`: audio minutes, prompt and completion tokens,
   provider calls, wall-clock per call, and how many of the twenty scored,
   skipped or failed and why. Put the vendors' published prices into the three
   price settings; `GET /analysis/status` then reports real money.
5. Hand the client the measured per-call cost and the twenty scores. **Whether
   the caps are raised after that is their decision, not the build's.**

*DoD:* twenty calls through the whole pipeline; the measured-cost line exists in
`docs/ASSUMPTIONS.md`; the prices are entered and `priced` is `true`; the caps
are left wherever the client's answer puts them, and if there is no answer they
are left at 20 and the feature stays effectively off.

---

## 11. Risks

### 11.1 Cost per call — measured, not estimated

**This document contains no cost figure, and no implementer may invent one.**
Nobody has run BonviCall audio through these providers, the vendors' prices
change, and a number written here would be quoted back as a budget.

What phase 1 does instead is make the cost **measurable, per call, from day one**:

| Recorded | Where | Billing unit it corresponds to |
|---|---|---|
| `audio_bytes`, `audio_duration_ms` | `call_transcripts` | ASR is billed per second or per minute of audio |
| `prompt_tokens`, `completion_tokens` | `call_scores` | LLM is billed per input and output token |
| `asr_calls`, `llm_calls` | `call_analysis_state` | Requests against a quota; includes retries |

Three integer settings hold the price, all defaulting to **0**:
`analysis.price_asr_micro_usd_per_minute`,
`analysis.price_llm_micro_usd_per_1k_input_tokens`,
`analysis.price_llm_micro_usd_per_1k_output_tokens`. While they are zero,
`cost_micro_usd` is 0 and the status endpoint reports `priced: false` — the panel
then shows measured units and the words "narx kiritilmagan", not `$0.00`.

The number the client actually needs comes from task 12: twenty real calls, the
measured units, the vendors' published prices on that day, and one line in
`docs/ASSUMPTIONS.md`. After that the monthly cap (§4.5) means something real.

### 11.2 Calls with no audio, and very short calls

| Case | Handling |
|---|---|
| `has_audio = false` | Never queued (§2.6). Pressing the button gives `409 call_not_analysable`. Audio-less answered calls are a normal, measured population here — every one carries an `audio_missing_reason` and the gap report (UC-23) is the instrument that watches them. Analysis must not turn a capture problem into a second wall of analysis failures reporting the same thing. |
| Audio deleted by retention | `skipped` / `audio_expired`. A twelve-month-old call cannot be analysed and never will be. |
| `duration_sec < 30` | `skipped` / `call_too_short`. Also the cheapest possible protection: short calls are the most numerous and the least scorable. |
| Answered but silent (`capture_returned_silence`) | ASR returns empty text → `failed` / `transcript_empty`, which is **permanent** and deliberately outside `TRANSIENT_FAILURES`. Retrying it every night would buy the same empty answer at the same price. |
| Transcript far shorter than the audio | Scored, but `needs_review` with `short_transcript` — the rule that only works because `count_words()` strips `[MM:SS]` and `SPEAKER_n:` first, which in their code was a silent bug that exempted exactly the most suspicious calls. |

### 11.3 Rate limits and provider outages

Four layers, in the order they take effect: the in-process rate limiter → the
vendor-stated `Retry-After` honoured before any exponential guess → the provider
cooldown table, which stops the *next* call before it opens the audio → the
nightly transient retry, which is what stops a quota day becoming permanent
failure. Gemini's free tier is 500 requests/day and it returns 503 under
ordinary load, so both paths are exercised regularly rather than theoretically.

Visibility is the point: `GET /analysis/status` names the role in cooldown and
the seconds left, `waiting_retry` is counted apart from `failed`, and three
consecutive job failures raise `analysis_job_failed`. An AI pipeline that stops
quietly is worse than one that stops loudly, because nobody notices for a week.

**The residual risk that is not engineered away:** a provider can change a model
name or retire a model, and the failure appears only on the next call. Their
`catalog.py` existed for that and is not ported (§1.2). Mitigation for phase 1 is
the failure being visible and the model being a settings row an admin can change
without a deploy.

### 11.4 Blast radius on the running system

| Change | Radius | Mitigation |
|---|---|---|
| **Pydantic 2.10 → 2.13** | **Every request and every response of a live API.** The largest risk in this plan, and it has nothing to do with AI. | Task 1 is that change alone, deployed alone, reverted alone. Evidence it works: BonviZvonki runs 2.13.4 with the same FastAPI 0.115.6. `make contract` diff is the detector. |
| Three vendor SDKs in the image | Image size, CVE surface, and a pip resolution that can fail on rebuild | Lazy imports: a missing SDK is an error at call time, never at start-up. Pinned exactly. BonviZvonki has the scar for the opposite — a package installed by hand into a container, so the rebuild failed on a different machine. |
| Migration 010 | Four `CREATE TABLE`, five `CREATE TYPE`, two `ALTER TYPE ADD VALUE`, twenty-six `INSERT`s into `app_settings`. No existing table touched, no data rewritten, no lock held on `calls`. | `ALTER TYPE … ADD VALUE` needs `autocommit_block()` — migration 008 is the template. Read the migration before committing (global rule). |
| New `AlertKind` values | The panel's alert labels must know them or an alert renders as a raw string | The two labels are part of task 11's `uz.json` work. |
| The additive method on `modules/audio/service.py` | The module that serves audio playback to the panel and the app | Additive only: the diff adds a method and changes no line. The full audio suite runs in task 6's DoD. |
| Four new worker jobs | The worker process also runs `audio_retention`, which deletes recordings irreversibly | `analysis_run` is bounded (`analysis.call_timeout_sec`, a per-tick claim limit) and takes a distinct advisory lock, so it cannot block retention. Its cron slot is 01:45, deliberately not 02:00. With the flag off every job returns 0 immediately. |
| Two new panel permissions | `GET /auth/me` returns a longer list | Additive; the panel gates on presence. |
| `CallDetailPage.tsx` | The busiest page in the panel | One import, one element, behind a permission check. Without `analysis:read` the component is not mounted and no request is issued. |
| **The feature itself, once enabled** | Money leaves the account, and recordings of customer conversations are sent to a third party | `analysis.enabled` off by default; two monthly caps; a twenty-call trial run inside those caps before anything wider (task 12); and the decision to enable it at all — and later to raise the caps — belongs to the client, not to this plan. |

### 11.5 Audio leaves the server — the one thing this feature genuinely changes

Until now, a recording made by this product has never left the host. `SPEC` §8
builds an entire fail-closed privacy boundary on the phone so that a private
call is never captured in the first place; `STACK.md` keeps the audio on local
disk; the panel streams it same-origin. **This feature sends recordings of
customer conversations to a company in another country.** That is not a bug in
the plan — it is what the client asked for — but it is the first time it is
true, and it must be written down rather than discovered.

What the design does about it:

- **Only what the boundary already admitted.** Analysis reads
  `call_audio` rows and nothing else. A call the phone refused to record does
  not exist here, so the §8 boundary still decides what can ever be sent.
- **Only external, answered calls** (§2.6). Colleague conversations are not
  sent, and neither is anything from a fleet whose line directory is empty —
  because when we cannot tell the two apart, we send neither.
- **Nothing is sent twice.** Idempotency is enforced by a UNIQUE `call_id` and
  checked before every provider call; `force` is the only path that re-sends and
  it is admin-only.
- **Nothing is stored at the vendor by us.** The clients stream bytes into a
  single request; there is no file upload, no vendor-side asset id and nothing
  to delete afterwards. What the vendor retains under its own policy is the
  vendor's answer, not ours, and it is one of the questions step 2 of task 12
  puts in front of the client.
- **The transcript is the durable copy.** After analysis, the text lives here,
  under this product's retention and this product's RBAC.

What the design does **not** do, deliberately: it does not redact names or
numbers from the audio before sending, because a redaction that is only
approximate is worse than none — it would let everybody believe the problem was
solved. If the client needs that, it is its own phase with its own measurement.

---

## 12. Open questions — with the decision that stands if nobody answers

Each of these is decided. If the client says nothing, the recommendation is what
gets built.

**Q1 — May a salesperson see the AI score of their own call?**
*Decision: no.* `analysis:read` is not granted to `sales`, and the section does
not render for them. N41's transparency promise is "see your own calls and your
own phone's health"; an unreviewed machine score of one's own work is a
different thing, and showing it before any human has calibrated the rubric
invites a dispute the tool cannot win. Reversing it later is one line in the
registry plus a `:own` scope in the service query — and the review queue exists
precisely so that the scores which reach a person have been looked at first.

**Q2 — Should internal calls be transcribed?**
*Decision: no in phase 1* (§2.6). BonviZvonki did it for search and dispute
evidence; BonviCall has no search page yet, so it would be an ASR bill with no
reader. `analysis.transcribe_internal` exists, defaults to `false`, and flipping
it needs no deploy.

**Q3 — Editable rubric now or later?**
*Decision: later* (§2.5). The rubric is pinned in code as `v1`; every score
carries its version, so phase 2 can add the table and lose nothing. Shipping
rubric CRUD before a single call has been scored means tuning a rubric against
no evidence.

**Q4 — Where do vendor API keys live?**
*Decision: the environment* (§4.2), against BonviZvonki's precedent, because
`settings:read` — which a manager holds — would otherwise expose them. The cost
is that adding a key needs a container restart. That is the right trade for a
three-key, one-tenant deployment.

**Q5 — How often does the pipeline run?**
*Decision: dispatch every 5 minutes, run every 2 minutes* (§5), giving a score
roughly ten minutes after the recording lands. If the client would rather pay for
the day in one overnight batch, both are cron entries in `worker.py` and the
change is two lines — but a result that appears while the manager still remembers
the call is worth more than one that appears at 07:00.

**Q6 — What happens to an analysis when the audio expires at twelve months?**
*Decision: nothing.* Transcripts and scores outlive the audio (§2.3). Deleting
them would destroy the cheap, small record and keep only the expensive absence.
If the client's retention policy is meant to cover transcripts too, that is a
different rule and it needs its own setting and its own migration.

**Q7 — Is pressing "analyse" an audited action?**
*Decision: not in phase 1.* `AuditAction` is a closed enum and adding a value
costs a migration and an entry in the panel's audit labels. What the action
actually spends is already recorded per call — `attempts`, `asr_calls`,
`llm_calls`, `cost_micro_usd` on `call_analysis_state` — and `analysis:run` is
admin-only, so the set of people who could have pressed it is the set of
admins. The day `analysis:run` is granted to managers (Q1's neighbour), add
`AuditAction.ANALYSIS_REQUESTED` in the same change, because at that point
"who spent this" stops having an obvious answer.

**Q8 — Which provider actually gets used on day one?**
*Decision: Gemini for ASR, Anthropic for LLM* (§4.1), which is what the registry
defaults to and what BonviZvonki measured. The one thing that could change it is
the client having, or refusing, a particular vendor account — which is a
purchasing decision, not an engineering one, and task 12 is where it surfaces
with a real per-call number attached.
