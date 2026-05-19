# Ray Orchestrator: Page-Slicing Fan-Out Delta

**Branch:** `cau/ray-page-slicing` — changes against `main`
**Implemented in:** `docling-jobkit`; wired in `docling-serve`

This document is a diff companion to `ray-orchestrator-architecture.md`. It shows only what changed: new components, new communication patterns, moved lifecycle ownership, and the new internal type boundary. All sections that are unchanged (dispatcher, Redis key space, reconciliation, tenant fairness) are not repeated here.

Color key used in all diagrams below:

```
  green  = new on this branch
  amber  = existed before, responsibility or contract changed
  gray   = unchanged
```

---

## 1. Component Topology Delta

The single `DocumentProcessorDeployment` is replaced by two cooperating Ray Serve deployments. Everything else in the topology is unchanged.

```mermaid
flowchart TB
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef changed fill:#7a5500,color:#fff,stroke:#5a3d00
    classDef existed fill:#444,color:#fff,stroke:#222

    subgraph SERVE["docling-serve process  (unchanged)"]
        API["FastAPI"]
        ORCH["RayOrchestrator"]
        SUP["Dispatcher supervisor"]
        SUB["pub/sub listener"]
    end

    subgraph RAY["Ray cluster"]
        DISP["RayTaskDispatcher\n(unchanged)"]:::existed

        subgraph RS_NEW["Ray Serve — new two-deployment plane"]
            COORD["DoclingProcessorCoordinatorDeployment\n● owns parent task lifecycle\n● Redis handle · heartbeat\n● source materialization\n● fan-out / collect\nnum_cpus=0.5 · max_ongoing_requests=N\nno DoclingConverterManager"]:::new
            WORK["DoclingProcessorConverterDeployment\n● warm DoclingConverterManager\n● max_ongoing_requests=1\n● no Redis responsibility\n● converts one slice or one task"]:::new
            COORD -- "process_converter_request(ConverterRequest)\nRay Serve handle call" --> WORK
        end
    end

    PLASMA[("Ray Object Store\nplasma store · shared PDF bytes")]:::new
    REDIS[("Redis\nunchanged")]:::existed

    DISP -- "process_task(task)\n(contract unchanged)" --> COORD
    COORD -- "ray.put(pdf_bytes)" --> PLASMA
    WORK -- "ray.get(artifact_ref)" --> PLASMA
    COORD -- "STARTED · heartbeat · finalize · PUBLISH" --> REDIS
```

**Key ownership changes:**

| Responsibility | Before (`main`) | After (branch) |
|---|---|---|
| `process_task(task)` entry point | `DocumentProcessorDeployment` | `DoclingProcessorCoordinatorDeployment` ● |
| Redis STARTED + execution lease + heartbeat | `DocumentProcessorDeployment` | `DoclingProcessorCoordinatorDeployment` ● |
| `finalize_task_*_atomic` + PUBLISH | `DocumentProcessorDeployment` | `DoclingProcessorCoordinatorDeployment` ● |
| `DoclingConverterManager` (warm models) | `DocumentProcessorDeployment` | `DoclingProcessorConverterDeployment` ● |
| Source download / decode | `DocumentProcessorDeployment` | Coordinator (PDF fan-out path) ● |
| Per-slice page-range conversion | — did not exist — | `DoclingProcessorConverterDeployment` ● |

The split is explicit: the coordinator and converter are separate deployments with distinct responsibilities.

---

## 2. Communication Patterns

The baseline is a **single serial call** through one Serve deployment. The branch introduces a conditional **fan-out / collect** path inside the coordinator. There are now three distinct execution paths for a task.

### 2a. Passthrough path (unchanged behavior, new coordinator hop)

Applies to: non-PDF formats, multi-source tasks, CHUNK tasks, single-source PDFs with fan-out disabled or below the slice threshold.

```mermaid
flowchart LR
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef existed fill:#444,color:#fff,stroke:#222

    DISP(["Dispatcher"]):::existed
    COORD["Coordinator\nnew hop"]:::new
    WORK["Converter\nconverts as before"]:::new
    REDIS[("Redis\nfinalize · PUBLISH")]:::existed

    DISP -- "process_task(task)" --> COORD
    COORD -- "PassthroughTaskRequest" --> WORK
    WORK -- "ConverterTaskResult" --> COORD
    COORD -- "finalize_task_*_atomic\n+ PUBLISH" --> REDIS
```

Every task now passes through the coordinator, even when no materialization or fan-out occurs. This adds one Serve handle hop.

### 2b. Materialized PDF, no fan-out (effective pages ≤ `max_page_slice_size`)

Applies when `enable_pdf_page_slice_fanout=true` and the source is a single-source PDF whose effective page range fits in one slice. The source is downloaded/decoded once, placed in the plasma store, and the worker receives an `ObjectRef` instead of re-fetching the bytes.

```mermaid
flowchart LR
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef existed fill:#444,color:#fff,stroke:#222

    DISP(["Dispatcher"]):::existed
    COORD["Coordinator"]:::new
    MAT["materialize_and_preflight()\npreflight · page_count"]:::new
    PLASMA[("Ray plasma store\nray.put → ObjectRef")]:::new
    WORK["Converter\nray.get → convert full doc"]:::new
    REDIS[("Redis\nfinalize · PUBLISH")]:::existed

    DISP -- "process_task(task)" --> COORD
    COORD --> MAT
    MAT -- "ray.put(bytes)" --> PLASMA
    COORD -- "MaterializedConvertRequest\n(artifact_ref, filename, task)" --> WORK
    WORK -. "ray.get(artifact_ref)" .-> PLASMA
    WORK -- "ConverterTaskResult" --> COORD
    COORD -- "finalize + PUBLISH\ndel artifact_ref" --> REDIS
```

### 2c. Fan-out path (effective pages > `max_page_slice_size`)

Applies when `enable_pdf_page_slice_fanout=true` and the effective page count exceeds `max_page_slice_size`. The coordinator holds the `ObjectRef` for the full parent task duration while N parallel `SliceConvertRequest` calls run on converter replicas. After all slices are collected, the coordinator assembles the final document and finalizes the parent.

```mermaid
flowchart TB
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef existed fill:#444,color:#fff,stroke:#222
    classDef assem   fill:#0d4f6b,color:#fff,stroke:#093a52

    DISP(["Dispatcher"]):::existed
    REDIS[("Redis\nfinalize · PUBLISH")]:::existed
    PLASMA[("Ray plasma store\nshared ObjectRef")]:::new

    COORD["Coordinator\n① mark STARTED · write lease · start heartbeat\n② materialize_and_preflight()\n③ build SlicePlan\n④ ray.put(bytes) → ObjectRef"]:::new
    W1["Converter replica\nslice pages [1, S]"]:::new
    W2["Converter replica\nslice pages [S+1, 2S]"]:::new
    WN["Converter replica\n… slice N"]:::new
    ASSEM["Coordinator\n⑥ _assemble_slice_results()\n    sort by slice_index\n    DoclingDocument.concatenate()\n⑦ process_exportable_results()\n⑧ finalize + PUBLISH\n    cancel heartbeat · del ObjectRef"]:::assem

    DISP -- "process_task(task)" --> COORD
    COORD -- "ray.put(bytes)" --> PLASMA
    COORD -- "⑤ SliceConvertRequest\n(artifact_ref, page_range=[1,S],\n slice_index=0)" --> W1
    COORD -- "⑤ SliceConvertRequest\n(artifact_ref, page_range=[S+1,2S],\n slice_index=1)" --> W2
    COORD -- "⑤ SliceConvertRequest\n..." --> WN
    W1 -. "ray.get(artifact_ref)" .-> PLASMA
    W2 -. "ray.get(artifact_ref)" .-> PLASMA
    WN -. "ray.get(artifact_ref)" .-> PLASMA
    W1 -- "ExportableDocument\n(doc, status, errors,\n timings, page_range,\n slice_index=0)" --> ASSEM
    W2 -- "ExportableDocument\n(slice_index=1)" --> ASSEM
    WN -- "ExportableDocument\n(slice_index=N)" --> ASSEM
    ASSEM --> REDIS
```

Fan-out concurrency is always **bounded** by `max_page_slice_parallelism` using an `asyncio.wait` sliding-window refill loop. When `max_page_slice_parallelism` is unset, it defaults to `max_concurrent_tasks`.

---

## 3. Task Lifetime on Actors

On `main`, `DocumentProcessorDeployment` owns the full task lifecycle in sequence — STARTED, heartbeat, convert, export, finalize, PUBLISH — while holding its Serve slot (and GPU allocation) for the entire wall-clock duration. See base architecture §3 notes for details.

The branch splits that into two actors:

### Coordinator and converter — lifecycle after the split

```mermaid
flowchart TB
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef assem   fill:#0d4f6b,color:#fff,stroke:#093a52

    DISP(["Dispatcher"])

    subgraph COORD_BOX["DoclingProcessorCoordinatorDeployment  (new — no model weights)"]
        C1["mark STARTED\nwrite execution lease\nstart heartbeat asyncio.Task"]:::new
        CPATH{"fan-out\neligible?\n(PDF, single-source,\nfanout enabled)"}:::new
        C_MAT["materialize_and_preflight()\nray.put(bytes) → ObjectRef\nbuild SlicePlan"]:::new
        C_WAIT["bounded wait\nover N SliceConvertRequests"]:::new
        C_ASSEM["_assemble_slice_results()\nDoclingDocument.concatenate()"]:::assem
        C_EXPORT["process_exportable_results()\n→ DoclingTaskResult"]:::assem
        C_PASS["PassthroughTaskRequest\n→ unwrap ConverterTaskResult"]:::new
        C_FIN["finalize_task_*_atomic()\nPUBLISH\ncancel heartbeat\ndel ObjectRef"]:::new

        C1 --> CPATH
        CPATH -- "Yes, above threshold" --> C_MAT --> C_WAIT --> C_ASSEM --> C_EXPORT --> C_FIN
        CPATH -- "No" --> C_PASS --> C_EXPORT
    end

    subgraph WORK_BOX["DoclingProcessorConverterDeployment  (new — holds warm DoclingConverterManager)"]
        W_SLICE["ray.get(artifact_ref)\ncm.convert_documents(page_range=child_range)\n→ ExportableDocument"]:::new
        W_PASS["cm.convert_documents(task.sources)\n→ ConverterTaskResult"]:::new
    end

    DISP --> C1
    C_WAIT -- "SliceConvertRequest ×N\n(artifact_ref, page_range, slice_index)" --> W_SLICE
    W_SLICE -- "ExportableDocument" --> C_ASSEM
    C_PASS -- "PassthroughTaskRequest" --> W_PASS
    W_PASS -- "ConverterTaskResult" --> C_PASS
```

The coordinator holds its Serve slot for the **full parent task duration**, including while child slices are running. Because coordinator replicas carry no GPU or heavy model weights, the idle cost while awaiting child slices is a cheap coordinator slot, not a GPU slot.

---

## 4. Concurrency and Resource Blocking

### 4a. Deadlock protection

A classic Ray Serve deadlock occurs when a deployment replica waits on a call to its **own** deployment: the waiting replica holds its `max_ongoing_requests` slot, and if all slots are full, no new replicas are free to service the call it is waiting on, causing a hang.

The pre-branch single `DocumentProcessorDeployment` with `max_ongoing_requests=1` would deadlock the moment it tried to call itself in parallel. The two-deployment split eliminates this:

```mermaid
flowchart LR
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef existed fill:#444,color:#fff,stroke:#222

    subgraph POOL_C["Coordinator replica pool\n(separate Ray Serve deployment)"]
        C1["Coordinator replica 1\nwaiting on child slices"]:::new
        C2["Coordinator replica 2\nwaiting on child slices"]:::new
        CN["…"]:::new
    end

    subgraph POOL_W["Converter replica pool\n(separate Ray Serve deployment)"]
        W1["Converter replica 1\nconverting slice"]:::new
        W2["Converter replica 2\nconverting slice"]:::new
        WN["Converter replica N"]:::new
    end

    C1 -- "SliceConvertRequest" --> W1
    C2 -- "SliceConvertRequest" --> W2
    CN -- "SliceConvertRequest" --> WN
```

**Why deadlocks cannot occur:**
- Coordinator replicas and converter replicas are in **separate Ray Serve deployment pools**. Ray routes by deployment; a coordinator slot waiting on converters is never occupying a converter slot.
- Multiple coordinators can all be waiting simultaneously — each is async I/O blocked, not holding a thread or a converter slot.
- `max_ongoing_requests=1` on the converter is preserved for thread safety. It limits each converter replica to one slice at a time, but does not interact with coordinator occupancy.
- If all converter replicas are busy, new `SliceConvertRequest` calls queue in Ray Serve's internal backlog for the converter deployment. Coordinators wait async. No slots deadlock.

The only saturation risk is **pool exhaustion**: if `max_page_slice_parallelism` is unset and a very large PDF creates more in-flight slice requests than there are converter replicas, the excess queues in the converter backlog. Coordinators keep waiting; converters keep processing. No deadlock, but latency for other tasks increases until slices drain.

---

### 4b. Resource blocking while a large document is processing

The fan-out path changes which resources are held and for how long compared to the baseline single-document path.

```mermaid
flowchart TD
    classDef coord  fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef worker fill:#0d4f6b,color:#fff,stroke:#093a52
    classDef res    fill:#555,color:#fff,stroke:#333

    subgraph COORD["Coordinator slot — held for complete parent task duration"]
        C1["STARTED + lease + heartbeat"]:::coord
        C2["materialize + preflight\nray.put -> ObjectRef"]:::coord
        C3["await all slices\nasync blocked — not CPU-bound"]:::coord
        C4["assemble + export\nfinalize + del ObjectRef"]:::coord
        C1 --> C2 --> C3 --> C4
    end

    PLASMA[("plasma ObjectRef\nheld for full parent duration")]:::res
    REDIS[("Redis active_tasks\nheld for full parent duration")]:::res

    W1["Converter slot: slice 1\nray.get + convert\nreleased on completion"]:::worker
    W2["Converter slot: slice 2\nray.get + convert\nreleased on completion"]:::worker
    WN["Converter slot: slice N\nreleased on completion"]:::worker

    C2 --> PLASMA
    C3 --> W1 & W2 & WN
    W1 & W2 & WN --> C4
```

| Resource | Held from | Released | Count per parent | Blocking effect |
|---|---|---|---|---|
| **Coordinator replica slot** | task dispatch | `finalize_task_*_atomic` completes | 1 | 1 slot counts against `coordinator_max_ongoing_requests_per_replica`; coordinator carries no GPU/model weight, so slot cost is cheap |
| **Ray plasma ObjectRef** | `ray.put()` after preflight | `del artifact_ref` in coordinator `finally` | 1 | Plasma memory held for full parent lifetime; released even on failure or coordinator crash |
| **Redis `active_tasks`** | dispatcher admission | `finalize_task_*_atomic` | 1 (the parent) | Counts against tenant `max_concurrent_tasks`; child slices do **not** increment this counter |
| **Converter replica slot** | slice dispatch | slice `ExportableDocument` returned | Up to `max_page_slice_parallelism` (or all slices if unset) | Each converter slot is at `max_ongoing_requests=1`; held only for the duration of one slice, then released |
| **Execution heartbeat** | lease write | coordinator `finally` cancels asyncio task | 1 per parent | Async loop; negligible cost beyond Redis traffic |

**Key change from baseline** (see base architecture §3 notes for the baseline): on this branch the GPU-capable converter slot is held only for the duration of one slice, not the full parent conversion. The coordinator slot is held for the full duration but is cheap — 0.5 CPU, no model weights. Converter replicas that finish a slice are immediately available for slices from other parents.

---

## 5. Data Type Boundaries  

### New internal types introduced on the branch

```mermaid
flowchart TB
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef changed fill:#7a5500,color:#fff,stroke:#5a3d00
    classDef existed fill:#444,color:#fff,stroke:#222

    subgraph MAT["Coordinator: materialization boundary  (new)"]
        MS["MaterializedSource\n  content_bytes: bytes\n  page_count: int\n  filename: str"]:::new
        OBJ["ray.ObjectRef\n  (PDF bytes in plasma store)"]:::new
        MS -- "ray.put(content_bytes)" --> OBJ
    end

    subgraph REQ["Coordinator → Converter: ConverterRequest  (new)"]
        PT["PassthroughTaskRequest\n  kind='passthrough_task'\n  task: Task"]:::new
        MC["MaterializedConvertRequest\n  kind='materialized_convert'\n  artifact_ref: ObjectRef\n  filename: str\n  task: Task  (sources=[])"]:::new
        SC["SliceConvertRequest\n  kind='slice_convert'\n  artifact_ref: ObjectRef\n  filename: str\n  options: ConvertDocumentsOptions\n  page_range: tuple[int,int]\n  slice_index: int"]:::new
    end

    subgraph OUT["Converter → Coordinator: result boundary  (new)"]
        WT["ConverterTaskResult\n  task_result: DoclingTaskResult\n  (passthrough + materialized paths)"]:::new
        ED["ExportableDocument\n  file: PurePath\n  document_hash: str | None\n  status: ConversionStatus\n  errors: list[ErrorItem]\n  timings: dict[str, ProfilingItem]\n  document: DoclingDocument | None\n  page_range: tuple[int,int] | None  ← slice\n  slice_index: int | None            ← slice\n  (slice path only)"]:::new
    end

    subgraph PLAN["Coordinator internal: slice planning  (new)"]
        SP["SlicePlan\n  total_pages: int\n  slices: list[SliceSpec]\n  effective_page_range: tuple[int,int]"]:::new
        SS["SliceSpec\n  page_range: tuple[int,int]\n  slice_index: int"]:::new
        SP --> SS
    end

    PT --> WT
    MC --> WT
    SC --> ED
```

### ExportableDocument replaces ConversionResult across the export pipeline

This is the most pervasive type change. On `main`, `process_export_results()` accepted `Iterable[ConversionResult]` — a docling-internal type that bundles the converter's lazy `InputDocument` reference with the output. On the branch, the primary entry point is `process_exportable_results(exportable_documents: Iterable[ExportableDocument])`.

`ExportableDocument` is a plain Pydantic model — no `InputDocument` reference, no raw file handles — carrying only what the export pipeline needs: filename, hash, status, errors, timings, and an optional `DoclingDocument`. The old `process_export_results(conv_results)` is kept as a deprecated shim for non-Ray orchestrators.

```mermaid
flowchart LR
    classDef removed fill:#7a1a1a,color:#fff,stroke:#5a0f0f
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef existed fill:#444,color:#fff,stroke:#222

    subgraph BEFORE["Before (main)"]
        CR["ConversionResult\ndocling-internal\n  input: InputDocument\n    (file handle · lazy pages)\n  document: DoclingDocument\n  status · errors · timings\nConsumed immediately\ninside single deployment"]:::removed
    end

    subgraph AFTER["After (branch)"]
        ED2["ExportableDocument\nplain Pydantic · serializable\n  file: PurePath  (no handle)\n  document: DoclingDocument | None\n  status · errors · timings\n  page_range | None  ← slice-aware\n  slice_index | None ← slice-aware\nCrossed coordinator→converter boundary\nAlso used for assembled result"]:::new
    end

    BEFORE -- "replaced by" --> AFTER

    PE["process_export_results()\ndeprecated shim"]:::removed
    PER["process_exportable_results()\nnew primary entry point"]:::new
    PE -- "wraps" --> PER
```

**Why this matters for fan-out:** `ConversionResult` is tied to a single converter run and carries a live `InputDocument`. `ExportableDocument` is a data-only snapshot that can represent a reassembled slice (produced by `_assemble_slice_results`) and fed into the same export helpers without any knowledge of slicing at the export layer.

### Naming delta: plan vs. implementation

The plan used "chunk" terminology throughout. The implementation uses "slice".

| Plan name | Implemented name |
|---|---|
| `ChunkResult` | `ExportableDocument` (unified with the export pipeline type) |
| `ChunkSpec` | `SliceSpec` |
| `SplitPlan` | `SlicePlan` |
| `chunk_convert` request variant | `SliceConvertRequest` |
| `enable_pdf_page_chunk_fanout` | `enable_pdf_page_slice_fanout` |
| `max_page_chunk_size` | `max_page_slice_size` |
| `max_page_chunk_parallelism` | `max_page_slice_parallelism` |

`ChunkResult` was also **merged into** `ExportableDocument` rather than kept as a separate type — the same model is used as the per-slice worker return value (with `page_range` and `slice_index` set) and as the assembled result fed into the export pipeline (those fields `None`).

---

## 6. Deployment Configuration Delta

### New config knobs (`RayOrchestratorConfig`)

```python
enable_pdf_page_slice_fanout: bool = False        # master gate
max_page_slice_size: int = 10                     # pages per child slice
max_page_slice_parallelism: Optional[int] = None  # concurrent in-flight slices cap

# Coordinator-specific resource overrides (normalized at startup if None)
coordinator_target_requests_per_replica: Optional[int] = None
coordinator_max_ongoing_requests_per_replica: Optional[int] = None
coordinator_num_cpus: Optional[float] = None      # defaults to 0.5
coordinator_memory_limit: Optional[str] = None    # defaults to ray_memory_limit_per_actor
```

Existing autoscaling knobs (`min_actors`, `max_actors`, `upscale_delay_s`, `downscale_delay_s`, `graceful_shutdown_*`) are **shared** between coordinator and converter — both deployments use the same scaling bounds.

### Deployment wiring (`create_deployment`)

Before: `deploy_processor()` produced a single `DocumentProcessorDeployment` handle.

After: `create_deployment()` produces a coordinator–converter pair wired via Ray Serve's `.bind()` DAG, with the converter handle injected into the coordinator constructor. The dispatcher still calls `process_task(task)` on the same handle — the deployment split is invisible to the dispatcher.

---

## 7. Failure Mode Additions

The existing failure modes (replica OOM, dispatcher death, Redis unavailable) are unchanged. Two new coordinator-specific behaviors:

### Fan-out setup failure (catches before any child launches)

```mermaid
flowchart TD
    classDef new    fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef fail   fill:#7a1a1a,color:#fff,stroke:#5a0f0f

    MAT["materialize_and_preflight() raises\nMaterializationLimitExceededError\nor MaterializationError"]:::fail
    FIN["finalize_task_failure_atomic\nPUBLISH FAILURE"]:::new
    DONE(["task → FAILURE\nno ObjectRef created\n(released in finally if partially created)"]):::fail

    MAT --> FIN --> DONE
```

`MaterializationLimitExceededError` is a structured subclass of `MaterializationError`. Both map to task FAILURE before any `SliceConvertRequest` is sent.

### Partial child failure (some slices fail, some succeed)

```mermaid
flowchart TD
    classDef new     fill:#1e5c1e,color:#fff,stroke:#0f3a0f
    classDef success fill:#1a5c1a,color:#fff,stroke:#0f3a0f
    classDef partial fill:#7a5500,color:#fff,stroke:#5a3d00
    classDef fail    fill:#7a1a1a,color:#fff,stroke:#5a0f0f

    WAIT["_run_slice_plan()\nawait all slice futures\n(exceptions caught per slice)"]:::new
    SFAIL["failed slices\n→ ExportableDocument\n   status=FAILURE\n   errors=[...]"]:::fail
    SSUCC["successful slices\n→ ExportableDocument\n   status=SUCCESS"]:::success

    CHECK{"any\nsuccessful\nslice?"}

    CONCAT["_assemble_slice_results()\nDoclingDocument.concatenate()\nassembled status=PARTIAL_SUCCESS\n(errors carry all child errors)"]:::partial
    EXPORT["process_exportable_results()\n→ DoclingTaskResult"]:::new
    FIN_OK["finalize_task_success_atomic\nPUBLISH SUCCESS\ntask-level status = SUCCESS"]:::success
    FIN_FAIL["finalize_task_failure_atomic\nPUBLISH FAILURE\ntask-level status = FAILURE"]:::fail

    WAIT --> SFAIL & SSUCC
    SFAIL & SSUCC --> CHECK
    CHECK -- "Yes (at least one)" --> CONCAT --> EXPORT --> FIN_OK
    CHECK -- "No (all failed)" --> FIN_FAIL
```

Task-level `TaskStatus` remains binary (`SUCCESS` / `FAILURE`). Partial page coverage is expressed in the result document's `ConversionStatus.PARTIAL_SUCCESS`, not in `TaskStatus`.

---

## Source Pointers (branch additions)

| Component | File |
|---|---|
| Coordinator deployment | `docling_jobkit/orchestrators/ray/serve_deployment.py` — `DoclingProcessorCoordinatorDeployment` |
| Converter deployment | `docling_jobkit/orchestrators/ray/serve_deployment.py` — `DoclingProcessorConverterDeployment` |
| Source materialization + preflight | `docling_jobkit/convert/materialization.py` |
| Slice / converter request models | `docling_jobkit/orchestrators/ray/models.py` — `SliceSpec`, `SlicePlan`, `ConverterRequest`, … |
| Exportable document type | `docling_jobkit/datamodel/exportable_document.py` |
| New export pipeline entry point | `docling_jobkit/convert/results.py` — `process_exportable_results()` |
| Fan-out config knobs | `docling_jobkit/orchestrators/ray/config.py` |
| Settings wire-up | `docling_serve/settings.py`, `docling_serve/orchestrator_factory.py` |
