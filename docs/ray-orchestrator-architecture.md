# Ray Orchestrator Architecture

Scope: `docling-serve` API layer through `docling-jobkit` Ray path — from an incoming conversion request to a durable result in Redis.

Each diagram has a single intent. Read them in order to build up the full picture.

---

## 1. Component Topology

What processes/actors exist, which host boundary they belong to, and what kind of communication connects them.

```mermaid
flowchart TB
    subgraph SERVE["docling-serve process"]
        API["FastAPI\nroutes + response shaping"]
        ORCH["RayOrchestrator\nenqueue · status · result"]
        SUP["Dispatcher supervisor\nhealth + rebind + init loop"]
        SUB["pub/sub listener\ndrives WebsocketNotifier"]
    end

    subgraph RAY["Ray cluster"]
        DISP["RayTaskDispatcher\ndetached named actor\nruns dispatch loop"]
        subgraph RS["Ray Serve — docling_processor"]
            P1["DocumentProcessorDeployment\nreplica 1"]
            PN["replica 2…N\nautoscaled"]
        end
    end

    REDIS[("Redis\nqueue · state · results · pub/sub")]

    API --> ORCH
    SUP -- "get_health / refresh_runtime RPC" --> DISP
    SUB -- "SUBSCRIBE docling:ray:updates" --> REDIS

    ORCH -- "HSET task metadata\nRPUSH tenant queue" --> REDIS
    ORCH -- "GET result blob" --> REDIS

    DISP -- "LPOP · dispatch_atomic\nreconcile" --> REDIS
    DISP -- "process_task.remote()" --> RS

    P1 -- "HSET STARTED · write lease\nheartbeat · finalize · PUBLISH" --> REDIS
    PN -- "same" --> REDIS
```

Key ownership boundaries:
- **`docling-serve`** is the only component that accepts HTTP and returns results to clients.
- **`RayTaskDispatcher`** is a detached Ray actor — it survives API pod restarts.
- **`DocumentProcessorDeployment`** replicas are managed by Ray Serve autoscaling.
- **Redis** is the system of record for all task state. Every other component is stateless with respect to task ownership.

---

## 2. Data Types Across Boundaries

What types flow between components at each handoff — from raw HTTP input to the final response body.

```mermaid
flowchart TB
    subgraph IN["Client → API boundary"]
        REQ["sources\n  HttpSource | FileSource | S3Coordinates\n  DocumentStream (inline bytes)\nconvert_options: ConvertDocumentsOptions\ntarget: InBodyTarget | S3Target | LocalPathTarget\ntask_type: CONVERT | CHUNK"]
    end

    subgraph ENV["API → Redis boundary  (durable task envelope)"]
        TASK["Task\n  task_id: uuid4\n  sources: list[TaskSource]\n    DocumentStream is re-encoded as FileSource(base64)\n    before Redis write — no raw file bytes in queue\n  target: TaskTarget\n  convert_options: ConvertDocumentsOptions\n  chunking_options: HierarchicalChunkerOptions | ...\n  metadata: {tenant_id: str}\n  task_status: TaskStatus  (PENDING on creation)"]
    end

    subgraph RKEY["Redis → Dispatcher → Replica boundary"]
        PASS["Task  (same object, LPOP-deserialized)\npassed verbatim to process_task.remote(task)"]
    end

    subgraph INTERNAL["Inside replica  (no I/O crossing)"]
        CONV["DoclingConverterManager.convert_documents(Task.sources)\n  → Iterable[ConversionResult]  per-document, lazy\n      .document: DoclingDocument\n      .status: ConversionStatus\n      .errors: list[ErrorItem]\n  → process_export_results() or process_chunk_results()\n  → DoclingTaskResult"]
    end

    subgraph RES["Replica → Redis boundary  (result store)"]
        RESULT["DoclingTaskResult\n  result: ExportResult           ← inline converted docs\n        | ZipArchiveResult        ← zip archive bytes\n        | RemoteTargetResult      ← written to S3/GDrive, no blob\n        | ChunkedDocumentResult   ← chunk list + export docs\n  processing_time: float\n  num_converted / num_succeeded / num_failed: int"]
    end

    subgraph PUBSUB["Replica → pub/sub boundary"]
        UPDATE["TaskUpdate  (JSON)\n  task_id: str\n  task_status: TaskStatus\n  result_key: str | None\n  error_message: str | None"]
    end

    subgraph OUT["API → Client boundary  (response_preparation.py)"]
        HTTP["ExportResult        → ConvertDocumentResponse   (JSON body)\nZipArchiveResult    → Response(application/zip)    (binary)\nRemoteTargetResult  → PresignedUrlConvertDocumentResponse\nChunkedDocumentResult → ChunkDocumentResponse       (JSON body)"]
    end

    REQ --> ENV
    ENV --> RKEY
    RKEY --> INTERNAL
    INTERNAL --> RES
    INTERNAL --> PUBSUB
    RES --> OUT
```

Notes:
- `DocumentStream` (in-memory bytes from a caller that passed raw file content) is converted to `FileSource` with a base64-encoded body before the `Task` is pushed to Redis. The queue never contains raw file handles.
- `ConversionResult` is a docling-internal type that never crosses a network or Redis boundary. It is the lazy per-document output of the docling converter, consumed immediately inside the replica by `process_export_results()` or `process_chunk_results()` to produce `DoclingTaskResult`.
- `RedisTaskMetadata` (stored in `task:{id}` HASH) is a separate, leaner structure written in parallel with the queue push — it holds status, timestamps, tenant_id, and task_size for fast status lookups and reconciliation, without the full payload.
- The `result` field in `DoclingTaskResult` is a discriminated union. `response_preparation.py` switches on the concrete type to pick the correct HTTP response shape.
- For `RemoteTargetResult` (S3/GDrive target), the result blob contains no document content — the replica has already pushed the output to the remote target, and the HTTP response is just a delivery confirmation.

---

## 3. Happy-Path Request Flow

One request from HTTP call to result retrieval, no failures.

```mermaid
sequenceDiagram
    participant C as Client
    participant API as docling-serve
    participant R as Redis
    participant D as Dispatcher
    participant P as Replica

    C->>API: POST /v1/convert/*
    Note over API: normalize · validate · resolve tenant_id

    API->>R: HSET task:{id} status=PENDING
    API->>R: RPUSH tenant:{T}:tasks  (serialized Task)
    API->>R: increment queued counter in tenant:{T}:limits
    API-->>C: task_id  [async] or enter poll loop [sync]

    Note over D: dispatch loop wakes (every dispatcher_interval)
    D->>R: reconcile active-task set
    D->>R: peek tenant queues + check capacity
    D->>R: dispatch_task_atomic  (LPOP + SADD active_tasks + write dispatch hash)
    D->>P: process_task.remote(task)  [fire-and-forget]

    Note over P: waits in Ray Serve backlog if all replicas busy

    P->>R: HSET task:{id} status=STARTED
    P->>R: HSET task:{id}:execution  (replica lease + initial heartbeat)

    loop every heartbeat_interval
        P->>R: update_task_execution_heartbeat
    end

    P->>P: convert / chunk documents

    P->>R: finalize_task_success_atomic
    Note over R: SETEX result blob · SET status=SUCCESS\ndecrement active counter · DEL dispatch+execution keys
    P->>R: PUBLISH docling:ray:updates  (SUCCESS + result_key)

    Note over API: pub/sub listener receives update → notifies websocket subscribers
    API->>R: GET result blob
    API-->>C: conversion result
```

Notes:
- The replica's Serve slot (including its full CPU and GPU allocation) is held from `process_task.remote()` dispatch all the way through `finalize_task_success_atomic` — the complete wall-clock duration of the conversion. A single replica processes one task at a time.
- `max_ongoing_requests=1` (the default) is a **thread-safety requirement**, not a conservative tuning choice: `DoclingConverterManager` is not safe to call concurrently within one replica. Ray Serve autoscaling (`min_actors` / `max_actors`) is the primary throughput lever — each additional replica adds one parallel conversion slot.

---

## 4. Redis Key Space

Keys are grouped by scope. Each entry lists key pattern, data type, TTL policy, and who reads/writes it.

```mermaid
flowchart TB
    subgraph PT["Per-Tenant"]
        TQ["tenant:{T}:tasks\nLIST · no TTL\nPending queue — RPUSH by orchestrator\nDrained by dispatcher LPOP"]
        TA["tenant:{T}:active_tasks\nSET · no TTL\nSADD on dispatch · SREM on finalize\nRead by reconciliation"]
        TL["tenant:{T}:limits\nHASH · no TTL\nmax_concurrent_tasks + active/queued counters\nUpdated atomically by dispatch + finalize"]
        TS["tenant:{T}:stats\nHASH · no TTL\nCompleted/failed/doc counters\nWritten by replica after finalize"]
    end

    subgraph PK["Per-Task"]
        TM["task:{id}\nHASH · no TTL until cleanup\nstatus · timestamps · error\nWritten by orchestrator + replica"]
        TD["task:{id}:dispatch\nHASH + TTL=processing_ttl\nDispatcher ownership record\nDEL on finalize"]
        TE["task:{id}:execution\nHASH + TTL=processing_ttl\nReplica lease + heartbeat_at timestamp\nDEL on finalize · read by reconcile"]
        TR["docling:ray:results:task:{id}:result\nSTRING + TTL=results_ttl\nmsgpack DoclingTaskResult\nWritten by replica finalize · read by API"]
    end

    subgraph SH["Shared"]
        DH["dispatcher:heartbeat\nSTRING + TTL=dispatcher_heartbeat_ttl\nWritten each dispatcher loop tick\nRead by supervisor to detect dead dispatcher"]
        CH["docling:ray:updates\nPUB/SUB channel\nTaskUpdate messages (status · result_key · error)\nPublished by replica or dispatcher · subscribed by orchestrator"]
    end
```

State interpretation:
- A task has only `tenant:{T}:tasks` entry → queued, not yet admitted.
- A task has `task:{id}:dispatch` → dispatcher admitted it, submitted to Ray Serve (status still PENDING until replica starts).
- A task has `task:{id}:execution` → a replica has claimed it and is heartbeating.
- `task:{id}:execution.heartbeat_at` going stale → replica is dead (see reconciliation).

---

## 5. Task State Machine

All states and transitions, happy path and failure paths combined.

```mermaid
stateDiagram-v2
    direction LR
    [*] --> PENDING : orchestrator.enqueue()

    PENDING --> STARTED : replica writes HSET status=STARTED\nand execution lease

    STARTED --> SUCCESS : replica finalize_task_success_atomic\nwrites result blob · publishes SUCCESS

    STARTED --> FAILURE : replica exception after retries\nOR reconcile: stale execution heartbeat\nOR reconcile: orphaned task\nfinalize_task_failure_atomic · publish FAILURE

    PENDING --> FAILURE : dispatcher _process_task_async\ncatches Ray dispatch exception before\nreplica ever claims the task

    SUCCESS --> [*] : on_result_fetched → expire result key\nafter result_removal_delay

    FAILURE --> [*] : result TTL expires\n(no result blob on failure)
```

Notes:
- `task:{id}` status stays `PENDING` for the entire window from enqueue through dispatch hash write — `STARTED` is only set once a replica actually begins work.
- The `finalize_task_*_atomic` operations are idempotent and compare-and-swap: if a replica succeeds just as the dispatcher is marking the same task as failed, the replica's SUCCESS wins and is preserved.

---

## 6. Dispatcher Admission Round

What the dispatcher executes on each `dispatcher_interval` tick.

```mermaid
flowchart TD
    TICK([Tick: dispatcher_interval elapsed])

    TICK --> RECON["Reconcile active-task set\nfor all tenants with active tasks"]
    RECON --> SCAN["Scan tenants with queued work"]
    SCAN --> EMPTY{Any tenant has\nqueued tasks?}
    EMPTY -- No --> DONE([Sleep until next tick])

    EMPTY -- Yes --> FOREACH["For each tenant\nin round-robin order"]

    FOREACH --> CHKCAP{tenant active_count\n< max_concurrent_tasks?}
    CHKCAP -- No --> NEXTT[Skip tenant]

    CHKCAP -- Yes --> PEEK["Peek next task in queue"]
    PEEK --> CHKLIM{check_tenant_can_process\ndoc count + queue limits OK?}
    CHKLIM -- No --> NEXTT

    CHKLIM -- Yes --> ATOMIC["dispatch_task_atomic\nLPOP + SADD active_tasks\n+ write dispatch hash"]
    ATOMIC --> SUBMIT["process_task.remote()\nfire-and-forget"]
    SUBMIT --> MORECAP{tenant still under cap\nand has more queued?}
    MORECAP -- Yes --> PEEK
    MORECAP -- No --> NEXTT

    NEXTT --> FOREACH
    FOREACH --> DONE
```

---

## 7. Failure Modes

### 7a. Conversion fails inside replica

The replica's `_process_convert_with_retry` raises after `max_task_retries` attempts.

- The exception propagates to `_process_task_async` in the dispatcher.
- `finalize_task_failure_atomic` is called: sets `task:{id}` status=FAILURE, decrements active counter, deletes dispatch + execution keys.
- FAILURE is published on pub/sub.
- No result blob is written; client polling reads status=FAILURE + error message.

### 7b. Replica OOM or hard crash

The Ray Serve replica process is killed or exits unexpectedly mid-task.

- Execution heartbeat stops updating `task:{id}:execution.heartbeat_at`.
- Dispatcher reconciliation (runs every round) detects `heartbeat_age > heartbeat_interval × 4`.
- `_fail_reconciled_task` → `finalize_task_failure_atomic` → FAILURE + publish.
- Ray Serve autoscaler starts a replacement replica.

```mermaid
flowchart TD
    S["STARTED\nexecution lease written · heartbeat running"]
    D["replica process dies\n(OOM, SIGKILL, node eviction)"]
    ST["heartbeat_at goes stale"]
    R["reconcile detects\nheartbeat_age > heartbeat_interval × 4"]
    F["finalize_task_failure_atomic\nFAILURE + publish"]

    S --> D --> ST --> R --> F
```

### 7c. Dispatcher actor dies or is restarted

The `RayTaskDispatcher` detached actor crashes.

- In-flight `_process_task_async` fire-and-forget coroutines are lost with the actor.
- Their tasks remain in `active_tasks` SET with no further activity.
- The supervisor in `docling-serve` detects the next health-check RPC failure; clears `self.dispatcher`.
- `_bind_dispatcher()` with `get_if_exists=True` + `max_restarts` triggers automatic Ray restart.
- On restart the dispatcher immediately runs `_reconcile_active_tasks`:
  - STARTED tasks with a stale execution heartbeat → FAILURE.
  - Dispatched-but-not-yet-STARTED tasks (no execution lease written yet) → left unresolved (conservative: they may still be in Ray Serve's backlog).
- Tasks still in `tenant:{T}:tasks` (never popped) are dispatched normally on the next round.

### 7d. Ray head unavailable (GCS lost)

The Ray GCS node dies, taking all Ray actors with it.

- RPCs to the dispatcher start timing out (`dispatcher_rpc_timeout`).
- The supervisor catches `DispatcherUnavailableError` and sets `_unhealthy_since`.
- After `liveness_fail_after` seconds of continuous failure, `is_liveness_healthy()` returns False → Kubernetes restarts the `docling-serve` pod.
- **Redis survives** — all task metadata and queued tasks are intact.
- New `docling-serve` pod calls `_initialize_ray_runtime()`, reconnects to a recovered Ray cluster, reattaches to the dispatcher actor, and dispatch resumes.

```mermaid
flowchart TD
    D["Ray head dies (GCS lost)\nall Ray actors unreachable"]
    T["RPC timeout → DispatcherUnavailableError\nsupervisor records _unhealthy_since"]
    L["after liveness_fail_after seconds\nliveness probe returns False"]
    R["Kubernetes restarts docling-serve pod"]
    N["new pod: _initialize_ray_runtime()\nreconnects to recovered Ray cluster\nreattaches to dispatcher actor"]
    Q["dispatcher resumes\nfrom durable Redis queue"]

    D --> T --> L --> R --> N --> Q
```

### 7e. Dispatcher RPC timeout (transient)

An isolated RPC call to the dispatcher times out but the actor is still alive.

- Supervisor clears `self.dispatcher` reference and retries in 1 second.
- New tasks written to Redis during the gap are safe — queue is durable.
- No tasks are lost; dispatch resumes automatically.

### 7f. Redis unavailable

All components that touch Redis will surface errors, but at different layers:

- `orchestrator.enqueue()` fails → HTTP 503 to client (no task created).
- Dispatcher reconcile/dispatch operations fail → exception logged, loop sleeps and retries.
- Replica heartbeat/finalize operations fail → task may be left stuck in STARTED; reconciliation will eventually clean it up once Redis recovers.

---

## 8. Multi-Tenant Fairness and Autoscaling

```mermaid
flowchart LR
    subgraph Enqueue["Incoming work (any mix of tenants)"]
        A1["Tenant A: task 1"]
        A2["Tenant A: task 2"]
        A3["Tenant A: task 3"]
        B1["Tenant B: task 1"]
        B2["Tenant B: task 2"]
    end

    subgraph Queues["Redis per-tenant queues"]
        QA["tenant:A:tasks\n[A1, A2, A3]"]
        QB["tenant:B:tasks\n[B1, B2]"]
    end

    subgraph Dispatch["Dispatcher round-robin"]
        DA["Admit A tasks\nuntil A reaches max_concurrent_tasks"]
        DB["Admit B tasks\nuntil B reaches max_concurrent_tasks"]
    end

    subgraph Serve["Ray Serve"]
        BL["Internal backlog\n(if all replicas busy)"]
        R1["Replica 1"]
        R2["Replica 2"]
        RN["Replica N"]
    end

    A1 & A2 & A3 --> QA
    B1 & B2 --> QB
    QA --> DA
    QB --> DB
    DA & DB --> BL
    BL --> R1 & R2 & RN
```

Notes:
- Dispatcher enforces **per-tenant** `max_concurrent_tasks` before submitting to Ray Serve; this is the primary backpressure mechanism.
- In a single round, a tenant can receive multiple dispatches if it still has capacity after its first task is submitted.
- Autoscaling of replicas is managed by Ray Serve (`min_actors` / `max_actors` / `target_requests_per_replica`). The dispatcher does not control replica count.
- Queue position returned by the API reflects the tenant queue depth, not the Ray Serve backlog — it is approximate.

---

## Source Pointers

| Component | File |
|-----------|------|
| FastAPI routes, lifespan, enqueue path | `docling_serve/app.py` |
| Orchestrator: enqueue, supervisor, pub/sub | `docling_jobkit/orchestrators/ray/orchestrator.py` |
| Dispatcher actor: dispatch loop, reconcile | `docling_jobkit/orchestrators/ray/dispatcher.py` |
| Replica: process_task, heartbeat, finalize | `docling_jobkit/orchestrators/ray/serve_deployment.py` |
| Redis atomics, key layout, pub/sub | `docling_jobkit/orchestrators/ray/redis_helper.py` |
| Config knobs | `docling_jobkit/orchestrators/ray/config.py` |
