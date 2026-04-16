# Hardening Plan for Ray Dispatcher Survival and API Validity

## Summary

Apply the hardening changes in five ordered steps so each step improves the system independently:

1. Fix existing correctness bugs in Redis state handling.
2. Make Ray task status durable across API restarts.
3. Convert `RayTaskDispatcher` into a named detached singleton with a local supervisor.
4. Reject new Ray work when the dispatcher is unavailable.
5. Add startup and steady-state reconciliation for leaked active tasks.

This pass stays inside `docling-jobkit` and `docling-serve` code. It does **not** include Helm/chart changes, and it explicitly **defers replica heartbeats** unless later validation shows they are necessary.

The plan is aligned with Ray docs:
- use a named detached actor in a namespace
- use Ray’s documented `get_if_exists=True` get-or-create flow
- treat actor-local state as lost on restart and recover from Redis
- keep the dispatcher as an async actor with non-blocking methods and explicit concurrency guards

## Implementation Changes

### Step 1. Silent bug fixes and state cleanup hardening

- Fix Redis timestamp writes in the Ray path:
  - `set_task_metadata()` must write a real UTC timestamp for `created_at`
  - `update_task_status()` must write a real UTC timestamp for `last_update_at`
  - stop storing the literal string `"null"` in those fields
- Fix the orphan-recovery helper mismatch:
  - add a real tenant-named helper or rename the existing helper so dispatcher recovery no longer calls a missing method
  - standardize on `tenant_id` naming in the Ray Redis helper API
- Fix orphan cleanup so missing `processing_state` does not still try to read `processing_state["task_size"]`
  - use durable task metadata when available
  - fall back to `1` with a warning for legacy tasks
- Make `complete_task_atomic()` the authoritative cleanup path for `task:{id}:processing`
  - delete the processing key there as an idempotent operation
  - keep the existing best-effort delete in the Serve replica `finally` block, but no longer rely on it for correctness
- Replace the hard-coded `7200s` processing-key TTL with a value derived from task limits rather than a fixed constant
  - do **not** lower this blindly to `120s` in this hardening pass, because there is no processing heartbeat yet and legitimate long tasks must not expire their processing key mid-run
  - default rule: `processing_ttl = task_timeout + 300s` when `task_timeout` is set, otherwise keep a conservative fallback larger than expected task runtime

### Step 2. Durable Ray task status

- Extend Ray task metadata written at enqueue to include:
  - `task_type`
  - `task_size`
  - `created_at`
  - `last_update_at`
- Override Ray `get_raw_task()` to fall back to Redis when `self.tasks` misses
  - reconstruct a minimal `Task` from Redis metadata
  - repopulate `self.tasks` from the Redis record
- Override Ray `task_status()` to use the same Redis-backed resolution path instead of only returning the in-memory entry
- Keep result retrieval unchanged; this step is about status continuity and removal of false `404`s after API restart

### Step 3. Named singleton dispatcher with local supervision

- Change dispatcher ownership from anonymous actor-per-API-process to a named detached actor in the configured Ray namespace
- Use Ray’s documented get-or-create pattern:
  - `RayTaskDispatcher.options(name=..., lifetime="detached", get_if_exists=True, max_restarts=..., max_task_retries=...).remote(...)`
  - do not implement a manual `get_actor`/create race
- Add exactly two actor RPCs:
  - `refresh_runtime(deployment_handle, config)` to update Serve handle/config after API startup
  - `get_health()` which must:
    - report whether the dispatch loop is running
    - idempotently start the loop if it is not running
- Keep the dispatcher as an async actor and move dispatch-loop lifetime inside the actor
  - no long-lived awaited `start_dispatching.remote()`
  - actor methods must remain non-blocking from Ray’s perspective and use `await`, not blocking `ray.get`
- Add an actor-internal concurrency guard such as an `asyncio.Lock` so concurrent `get_health()` and `refresh_runtime()` calls cannot race loop startup or runtime refresh
- Replace `_start_dispatcher()` in `RayOrchestrator` with a local supervisor task that:
  - binds to the named dispatcher
  - calls `refresh_runtime(...)` on startup
  - polls `get_health()` periodically
  - reacquires the named actor if the handle becomes invalid
- Make `RayOrchestrator.shutdown()` local-only by default
  - cancel the local supervisor and pub/sub tasks
  - disconnect local Redis clients
  - do **not** stop the shared dispatcher actor
  - do **not** call `serve.delete("docling_processor")`
- If tests need destructive cleanup, add a separate explicit test-only cleanup path rather than overloading normal shutdown

### Step 4. Admission control for invalid dispatcher states

- Add a Ray-specific `DispatcherUnavailableError`
- Add `ensure_dispatcher_ready()` to the Ray orchestrator and call it before any enqueue writes to Redis
- `ensure_dispatcher_ready()` should require only two conditions:
  - the named dispatcher actor is reachable
  - `get_health()` reports the loop running
- If either condition fails, raise `DispatcherUnavailableError` before `set_task_metadata()` or queue push
- In `docling-serve`, map `DispatcherUnavailableError` to HTTP `503` with `Retry-After: 1`
- Apply the same guard to sync endpoints that internally enqueue then wait

### Step 5. Reconciliation without replica heartbeats

- Remove heartbeat-age gating as the trigger for recovery
- Run reconciliation:
  - once before dispatching begins
  - periodically during steady state
- Reconciliation policy in this hardening pass:
  - if an active task has durable metadata with `status=started` and its `task:{id}:processing` key is missing, mark `FAILURE`, clear `dispatch_state`, publish update, release capacity
  - if an active task is still pre-start (`pending` / `dispatched`) and has no processing key, leave it unresolved
  - `status=processing`: leave it alone in this hardening pass unless the key is gone
- Resync tenant counters from canonical Redis structures after each tenant reconciliation:
  - `active_tasks = SCARD(active_tasks)`
  - `queued_tasks = LLEN(tasks)`
  - `active_documents = SUM(task_size for active task ids, using durable metadata where available)`

### Deferred Step 6. Only if Step 5 is insufficient

- Do **not** implement Redis replica heartbeats in this hardening pass
- First validate whether Serve-level timeout/health configuration solves remaining failure modes
- Important Ray Serve constraint:
  - do not assume `request_timeout_s` is a documented per-deployment fix for this dispatcher-to-`DeploymentHandle` path
  - treat it as a separate later investigation, not as the initial recovery mechanism
- If Serve-managed replica health is added later, use documented Serve hooks and config:
  - `check_health`
  - `health_check_period_s`
  - `health_check_timeout_s`
- Only add replica heartbeats if real failures remain that are not covered by:
  - missing processing key detection
  - validated Serve timeout/health behavior

## Public / Interface Changes

- New Ray orchestrator exception: `DispatcherUnavailableError`
- Ray dispatcher actor interface changes to:
  - `refresh_runtime(deployment_handle, config)`
  - `get_health()`
- Ray `task_status()` and `get_raw_task()` semantics change from memory-only to memory-plus-Redis fallback
- Normal `RayOrchestrator.shutdown()` semantics change to local cleanup only

## Test Plan

- Step 1:
  - metadata timestamps are real timestamps, not `"null"`
  - `complete_task_atomic()` deletes the processing key
  - missing processing state no longer crashes cleanup/recovery
- Step 2:
  - enqueue a Ray task, clear process-local `self.tasks`, and verify status is reconstructed from Redis instead of `404`
  - verify reconstructed tasks preserve status, task type, timestamps, and error message
- Step 3:
  - creating two Ray orchestrators in the same namespace binds both to the same named dispatcher
  - repeated startup uses `get_if_exists=True` semantics and does not create a second dispatcher
  - concurrent `refresh_runtime()` and `get_health()` calls do not race loop startup
  - local shutdown does not tear down the shared dispatcher or Serve deployment
- Step 4:
  - when dispatcher health fails, async Ray submission returns HTTP `503`
  - sync Ray submission also fails fast with HTTP `503` instead of enqueueing dead work
- Step 5:
  - active task with durable metadata `status=started` and a missing processing key becomes `FAILURE` and releases capacity
  - active task that is still pre-start (`pending` / `dispatched`) and has no processing key remains unresolved
  - tenant counters are resynced from Redis structures after reconciliation
  - existing stale-state incident shape (`active=N/N`, queued work blocked) is cleared automatically
- Regression:
  - normal Ray happy path still completes successfully
  - non-Ray orchestrators remain unchanged

## Assumptions and Defaults

- This plan is intentionally code-only; probe wiring in Helm is deferred.
- The recovery policy in this plan is `FAILURE + release capacity`, not requeue.
- Processing-key TTL must remain safely above legitimate task runtime until a real processing heartbeat exists.
- Replica heartbeats are explicitly deferred pending validation of Serve timeout/health behavior and real failure evidence.
- Detached actors are intentionally long-lived shared resources and must not be cleaned up by normal API shutdown.
- The dispatcher should continue receiving fresh Serve handles from the orchestrator via `refresh_runtime(...)`; do not make this hardening change depend on Serve DeveloperAPI handle lookup by name.

## Post-Validation Findings

Chaos validation exposed two remaining defects that must be fixed before this hardening can be considered complete.

### Finding 1. Dispatcher-unavailable failures can still bypass HTTP `503`

Observed behavior:
- async submission sometimes returned HTTP `500` instead of the intended HTTP `503`
- the failing stack passed through `ensure_dispatcher_ready()` and `_bind_dispatcher()`
- Ray then entered its own init / reconnect path and raised lower-level exceptions including `SystemExit: 15`

Why this is a problem:
- the API contract for invalid Ray dispatcher state is `503 Service Unavailable` with `Retry-After: 1`
- returning `500` means the hardening is not reliably containing dispatcher-unavailable conditions at the API boundary

Required fix:
- normalize all request-path dispatcher-binding / Ray-init failures into `DispatcherUnavailableError`
- this includes lower-level Ray exceptions that occur while binding the named dispatcher, including process-exit style failures raised from Ray internals
- no enqueue path may leak these failures as HTTP `500`

Acceptance criteria:
- when the Ray head or dispatcher is unavailable, async Ray submission returns HTTP `503`
- sync Ray submission that internally enqueues also returns HTTP `503`
- the response includes `Retry-After: 1`
- the same invalid-state scenario does not emit an unhandled ASGI traceback for the request

### Finding 2. API startup is still coupled to Ray availability through OTEL setup

Observed behavior:
- after Ray head disruption, the API process could become slow to restart or fail startup entirely
- `create_app()` eagerly called `get_async_orchestrator()` only to obtain the Ray Redis manager for OpenTelemetry setup
- that constructed `RayOrchestrator`, which immediately called `ray.init()`
- when the Ray head was unavailable, API startup failed before the app could serve requests

Why this is a problem:
- observability setup must not make API availability depend on Ray head availability
- this defeats the goal of graceful degradation: the API process should still start and return controlled `503` responses rather than crash-looping or hanging during boot

Required fix:
- remove the startup-time Ray dependency from OTEL wiring in `create_app()`
- `create_app()` must not require `get_async_orchestrator()` for metrics / instrumentation setup
- API process startup must succeed even while the Ray head is unavailable

Acceptance criteria:
- with the Ray head unavailable, the API process still starts successfully
- `/livez` remains healthy for the running process
- request paths that need Ray fail with controlled HTTP `503`, not startup failure
- OTEL / metrics wiring does not call `ray.init()` during ASGI app creation

### Finding 3. Killing the dispatcher actor can orphan an in-flight task in `started`

Observed behavior:
- killing the named detached `RayTaskDispatcher` actor during an active task did not permanently break admission
- the local supervisor detected dispatcher unhealthiness, rebound the named actor, and the replacement dispatcher became healthy again
- however, the in-flight task remained stuck in durable metadata as `status=started`
- the task kept its `task:{id}:processing` state, remained in the tenant active set, and never produced a result

Why this is a problem:
- dispatcher recovery currently restores control-plane health for new work, but does not restore ownership of already in-flight task completion
- the actual terminal success/failure writeback and `complete_task_atomic()` cleanup are currently performed by a fire-and-forget coroutine owned by the dispatcher actor
- when that actor dies, the coroutine dies with it
- reconciliation does not recover the task because the surviving `processing` key causes the current policy to treat the task as still live

Required fix:
- do not rely on dispatcher-actor-local background coroutine state as the only owner of terminal task completion
- make in-flight task completion durable across dispatcher actor death, or make stale `processing` state detectable so reconciliation can fail and release the task
- a surviving `processing` key must not be treated as sufficient evidence that a task is still making progress unless it is backed by a real execution heartbeat

Acceptance criteria:
- killing `RayTaskDispatcher` during an active task does not leave the task indefinitely stuck in `started`
- after dispatcher recovery, the affected task reaches a terminal state (`success` or `failure`) within a bounded recovery window
- tenant active-task capacity is released for the affected task
- if execution is no longer actually progressing, reconciliation can fail the task even when stale `processing` state remains
- a replacement dispatcher actor alone is not considered sufficient recovery unless in-flight task ownership is also restored or reconciled

### Finding 4. API pod restart can cause prolonged external `502` outage and loss of status visibility

Observed behavior:
- deleting the `docling-serve` API pod while a task was active terminated the old process with `SIGTERM`
- the old pod logged request / shutdown noise including `SystemExit: 15`, cancelled lifespan waits, and cancelled Ray client futures
- the replacement API pod eventually started and reconnected to Ray / Serve
- however, the public API stayed behind Cloudflare `502 Bad gateway` responses for an extended period
- the chaos harness timed out on `recovery_timeout_after=120.7s` because no successful status poll returned during that window

Why this is a problem:
- durable Redis-backed task status is not sufficient if clients cannot reach any healthy API instance to read it
- from the client perspective, task continuity is lost when the status endpoint disappears behind prolonged external `502`s
- this means API restart hardening is incomplete at the externally observable service boundary even if internal task state survives

Required fix:
- API pod replacement must not produce a prolonged external `502` window for status polling
- replacement pod startup and readiness must be fast enough that the public route continues to expose task status within a bounded recovery window
- normal pod termination during rolling replacement must not rely on request paths that emit unhandled tracebacks as part of expected shutdown

Acceptance criteria:
- restarting or deleting the active `docling-serve` pod during an in-flight task does not cause a prolonged external `502` outage
- `/v1/status/poll/{task_id}` becomes reachable again within a bounded recovery window well below the current `120s+` failure mode
- once the replacement pod is serving, the client can observe the task converge to a terminal state rather than timing out at the gateway layer
- pod replacement does not require manual intervention to restore externally visible status polling

## Appendix: Implemented State

This appendix records the implementation choices actually taken in `docling-jobkit` and `docling-serve`.

### Final Step Coverage

- Step 1: implemented
- Step 2: implemented
- Step 3: implemented
- Step 4: implemented
- Step 5: implemented
- Deferred Step 6: intentionally not implemented

### Implemented Step 5 Policy

Implemented reconciliation policy:
- if an active task has durable metadata with `status=started` and its `task:{id}:processing` key is missing, mark it `FAILURE`, clear `dispatch_state`, publish an update, and release capacity
- if an active task is still pre-start (`pending` / `dispatched`) and has no processing key, leave it unresolved
- if an active task has processing state with `status=processing`, leave it alone in this hardening pass
- after each tenant reconciliation, resync counters from canonical Redis structures

This means this hardening pass only auto-recovers tasks once downstream processing has actually started.

### Dispatcher Role Clarification

The dispatcher is not the authoritative execution queue for all downstream work. Its implemented role is:

- enforce fairness across tenants
- prevent a tenant from admitting more work than the configured limits allow
- move work from per-tenant Redis queues into Ray Serve in a fair order

With Ray Serve allowed to queue internally, a task counted as "active" may already be admitted downstream but not yet executing on a Serve replica. In practice, `max_concurrent_tasks` is therefore an admission-control bound at the dispatcher layer, not a strict "currently executing replica count".

### Implemented Interface Notes

- `RayTaskDispatcher` is a named detached actor created with `get_if_exists=True`
- `refresh_runtime(deployment_handle, config)` remains the runtime-refresh RPC
- `get_health()` is implemented as a boolean-returning RPC that idempotently starts the loop if needed
- `RayOrchestrator.shutdown()` is local-only; destructive shared cleanup exists only in the explicit test-only cleanup path
- `DispatcherUnavailableError` is raised before enqueue writes and mapped to HTTP `503` with `Retry-After: 1` in `docling-serve`

### Durable Metadata Notes

The implementation uses an internal `RedisTaskMetadata` model in `docling-jobkit` for Redis-backed reconstruction. This is intentionally separate from public `docling.datamodel.service` response/progress models because it carries internal persistence fields such as:

- `tenant_id`
- `task_size`
- `dispatch_state`
- `created_at`
- `last_update_at`
- `started_at`
- `finished_at`

It is an internal storage/recovery model, not part of the external service contract.
