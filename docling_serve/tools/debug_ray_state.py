#!/usr/bin/env python3
"""Debug script to inspect Ray Redis state and metrics.

Run this inside the container to diagnose dispatcher behavior:
    python3 -m docling_serve.debug_ray_state

Or as standalone script:
    python3 debug_ray_state.py
"""

import asyncio
import datetime
import os
import sys


async def debug_redis_state():  # noqa: C901
    """Check Redis state for Ray orchestrator."""
    # Add parent directory to path for imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from docling_jobkit.orchestrators.ray.redis_helper import RedisStateManager

    # Get Redis URL from environment
    redis_url = os.environ.get("DOCLING_SERVE_ENG_RAY_REDIS_URL")
    if not redis_url:
        print("❌ DOCLING_SERVE_ENG_RAY_REDIS_URL not set")
        return

    print("=" * 60)
    print("Ray State Inspector")
    print("=" * 60)
    print()
    print(f"✓ Redis URL: {redis_url}")
    print()

    # Create Redis manager
    redis_manager = RedisStateManager(
        redis_url=redis_url,
        results_ttl=3600,
        results_prefix="docling:ray:results",
        sub_channel="docling:ray:updates",
    )

    try:
        # Connect to Redis
        await redis_manager.connect()
        print("✓ Connected to Redis")

        # Check Redis ping
        ping_ok = await redis_manager.ping()
        print(f"✓ Redis ping: {ping_ok}")
        print()

        # Check dispatcher heartbeat
        print("Dispatcher Status:")
        print("-" * 50)
        heartbeat_age = await redis_manager.get_dispatcher_heartbeat_age()
        if heartbeat_age == float("inf"):
            print("  Heartbeat: NOT FOUND")
            print("  Status: ⚠️  UNKNOWN (dispatcher may not be running)")
        else:
            heartbeat_time = datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(seconds=heartbeat_age)
            print(
                f"  Heartbeat: {heartbeat_time.strftime('%Y-%m-%d %H:%M:%S')} UTC ({heartbeat_age:.1f}s ago)"
            )
            if heartbeat_age < 10:
                print("  Status: ✓ HEALTHY")
            elif heartbeat_age < 30:
                print("  Status: ⚠️  WARNING (heartbeat aging)")
            else:
                print("  Status: ❌ STALE (dispatcher may have crashed)")
        print()

        # Get all users with tasks (queued OR active)
        print("Users with Tasks:")
        print("-" * 50)
        users = await redis_manager.get_all_users_with_any_tasks()
        print(f"Found {len(users)} users: {users}")
        print()

        if not users:
            print("⚠️  No users found with tasks!")
            print("This could mean:")
            print("  1. No tasks have been submitted yet")
            print("  2. All tasks have completed and queues are empty")
            print("  3. Tasks are being tracked differently than expected")
            print()
        else:
            # Show breakdown of queued vs active
            queued_users = await redis_manager.get_all_users_with_tasks()
            active_users = await redis_manager.get_all_users_with_active_tasks()
            print(f"  Users with queued tasks: {len(queued_users)}")
            print(f"  Users with active tasks: {len(active_users)}")

            # Count tasks by state across all users using the same methods as metrics
            total_queued = 0
            total_dispatched = 0
            total_running = 0

            for tenant_id in users:
                # Use the same methods as the metrics collector
                user_queued = await redis_manager.get_tenant_queue_size(tenant_id)
                user_dispatched = await redis_manager.get_tenant_dispatched_task_count(
                    tenant_id
                )
                user_running = await redis_manager.get_tenant_running_task_count(
                    tenant_id
                )

                total_queued += user_queued
                total_dispatched += user_dispatched
                total_running += user_running

            print(f"  Tasks in queue (not dispatched): {total_queued}")
            print(
                f"  Tasks dispatched (not yet running, status=PENDING): {total_dispatched}"
            )
            print(
                f"  Tasks running (actively processing, status=STARTED): {total_running}"
            )
            print()

        # For each user, get details
        total_pending = 0
        total_active = 0
        total_capacity = 0

        for tenant_id in users:
            print(f"Tenant: {tenant_id}")

            # Get queue size
            queue_size = await redis_manager.get_tenant_queue_size(tenant_id)
            print(f"  Queue (pending): {queue_size} tasks")
            total_pending += queue_size

            # Get active task count from Redis Set (source of truth)
            active_count = await redis_manager.get_tenant_active_task_count(tenant_id)
            print(f"  Active (Redis Set): {active_count} tasks")

            # Get user limits (includes counter)
            limits = await redis_manager.get_tenant_limits(tenant_id)
            print(f"  Active (Counter): {limits.active_tasks} tasks")

            # Check reconciliation
            if active_count == limits.active_tasks:
                print("  ✓ Reconciliation: OK")
            else:
                print(
                    f"  ⚠️  Reconciliation: MISMATCH (Set={active_count}, Counter={limits.active_tasks})"
                )

            total_active += active_count

            # Get active task IDs
            if active_count > 0:
                print("\n  Active Tasks:")
                active_task_ids = await redis_manager.get_tenant_active_task_ids(
                    tenant_id
                )
                for task_id in active_task_ids[:10]:  # Show first 10
                    # Get task metadata to check dispatch_state and status
                    metadata = await redis_manager.get_task_metadata(task_id)
                    dispatch_state = metadata.get("dispatch_state", "unknown")
                    status = metadata.get("status", "unknown")

                    # Get processing state
                    processing_state = await redis_manager.get_task_dispatch_state_hash(
                        task_id
                    )
                    if processing_state:
                        dispatched_at = float(processing_state.get("dispatched_at", 0))
                        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
                        dispatched_ago = int(now - dispatched_at)

                        processing_started = processing_state.get(
                            "processing_started_at"
                        )
                        if processing_started:
                            processing_ago = int(now - float(processing_started))
                            print(
                                f"    - {task_id} (status={status}, dispatch={dispatch_state}, "
                                f"dispatched {dispatched_ago}s ago, processing {processing_ago}s)"
                            )
                        else:
                            print(
                                f"    - {task_id} (status={status}, dispatch={dispatch_state}, "
                                f"dispatched {dispatched_ago}s ago, not yet processing)"
                            )
                    else:
                        print(
                            f"    - {task_id} (status={status}, dispatch={dispatch_state}, "
                            f"⚠️  no processing state)"
                        )

                if len(active_task_ids) > 10:
                    print(f"    ... and {len(active_task_ids) - 10} more")

            print()

            # Show limits
            print("  Limits:")
            print(f"    Max concurrent: {limits.max_concurrent_tasks}")
            print(
                f"    Max queued: {limits.max_queued_tasks if limits.max_queued_tasks else 'unlimited'}"
            )
            print(
                f"    Max documents: {limits.max_documents if limits.max_documents else 'unlimited'}"
            )

            capacity_available = limits.max_concurrent_tasks - active_count
            total_capacity += limits.max_concurrent_tasks
            print(f"    Capacity available: {capacity_available}")
            print()

        # Orphaned tasks check
        print("Orphaned Tasks Check:")
        print("-" * 50)
        orphaned_found = False
        for tenant_id in users:
            active_task_ids = await redis_manager.get_tenant_active_task_ids(tenant_id)
            for task_id in active_task_ids:
                processing_state = await redis_manager.get_task_dispatch_state_hash(
                    task_id
                )
                if not processing_state:
                    if not orphaned_found:
                        print("⚠️  Orphaned tasks detected:")
                        orphaned_found = True
                    print(f"  - {task_id} (user: {tenant_id})")

        if not orphaned_found:
            print("✓ No orphaned tasks detected")
        print()

        # Summary
        print("Summary:")
        print("-" * 50)
        print(f"  Total users: {len(users)}")
        print(f"  Total in queue (not dispatched): {total_queued}")
        print(f"  Total dispatched (not yet running): {total_dispatched}")
        print(f"  Total running: {total_running}")
        print(f"  Total pending: {total_pending}")
        print(f"  Total active: {total_active}")
        if total_capacity > 0:
            utilization = (total_active / total_capacity) * 100
            print(
                f"  Total capacity used: {total_active}/{total_capacity} ({utilization:.1f}%)"
            )

        # Disconnect
        await redis_manager.disconnect()
        print()
        print("✓ Disconnected from Redis")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Run the debug checks."""
    asyncio.run(debug_redis_state())


if __name__ == "__main__":
    main()
