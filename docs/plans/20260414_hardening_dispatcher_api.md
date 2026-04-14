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
