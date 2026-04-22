"""
Autoscaler real VM test.

Actually creates and destroys VMs in OpenNebula by temporarily
overriding SLA thresholds in memory (no file changes needed).

HOW TO RUN:
    Make sure SSH tunnel is active, then:
        python scripts/test_autoscaler_real.py

WHAT IT DOES:
    1. Shows current VMs in OpenNebula
    2. Forces scale UP  — sets threshold to -1.0 so any CPU triggers it
    3. Waits for the VM to appear in OpenNebula
    4. Forces scale DOWN — sets idle window to 0s so it destroys immediately
    5. Waits for the VM to be removed
    6. Restores original SLA values
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.compute import sla
from api.compute.autoscaler import AutoScaler, _idle_since, AUTOSCALE_PREFIX
from api.compute.monitor import get_cluster_metrics
from opennebula.vm_manager import list_all_vms


def print_vms(label: str):
    vms = list_all_vms()
    print(f"\n  {label} ({len(vms)} VMs):")
    if not vms:
        print("    (none)")
    for vm in vms:
        print(f"    [{vm['one_vm_id']}] {vm['name']}  state={vm['state']}  cpu={vm['cpu_usage_pct']}%")


def wait_for_vm_count(target: int, timeout: int = 60):
    """Poll until OpenNebula has exactly `target` active/pending VMs or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        vms = [v for v in list_all_vms() if v["state"] in ("ACTIVE", "PENDING")]
        if len(vms) == target:
            return True
        time.sleep(3)
    return False


def wait_for_all_running(timeout: int = 90):
    """Poll until all VMs are ACTIVE with LCM_STATE=3 (RUNNING = fully booted)."""
    start = time.time()
    while time.time() - start < timeout:
        vms = list_all_vms()
        not_ready = [v for v in vms if not (v["state"] == "ACTIVE" and v["lcm_state"] == 3)]
        if not not_ready:
            return True
        print(f"    Still booting: {[v['name'] + ' lcm=' + str(v['lcm_state']) for v in not_ready]} ...")
        time.sleep(5)
    return False


def separator(title: str):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    # Save original SLA values to restore later
    original_scale_up   = sla.SCALE_UP_CPU_PCT
    original_scale_down = sla.SCALE_DOWN_CPU_PCT
    original_window     = sla.SCALE_DOWN_WINDOW_SEC

    scaler = AutoScaler()

    try:
        separator("STEP 1 — Current state")
        metrics = get_cluster_metrics()
        print(f"\n  Active VMs : {metrics['active_vms']}")
        print(f"  Avg CPU    : {metrics['avg_cpu_pct']}%")
        print_vms("VMs in OpenNebula")

        # ── Scale UP ──────────────────────────────────────────────────────────
        separator("STEP 2 — Force Scale UP")
        sla.SCALE_UP_CPU_PCT = -1.0   # any CPU > -1% triggers scale up
        print(f"\n  SCALE_UP_CPU_PCT overridden to {sla.SCALE_UP_CPU_PCT}")
        print("  Calling autoscaler check...")

        scaler._check_and_scale()
        print_vms("VMs immediately after check")

        print("\n  Waiting for all VMs to be fully RUNNING (up to 90s)...")
        if wait_for_all_running(timeout=90):
            print("  [OK] All VMs are now RUNNING")
        else:
            print("  [WARN] Some VMs not yet RUNNING — scale down may fail")
        print_vms("VMs after scale up")

        # ── Restore scale-up threshold ────────────────────────────────────────
        sla.SCALE_UP_CPU_PCT = original_scale_up
        print(f"\n  SCALE_UP_CPU_PCT restored to {sla.SCALE_UP_CPU_PCT}")

        # ── Scale DOWN ────────────────────────────────────────────────────────
        separator("STEP 3 — Force Scale DOWN")

        # Only possible if there are now more VMs than MIN_VMS
        current_vms = [v for v in list_all_vms() if v["state"] in ("ACTIVE", "PENDING")]
        if len(current_vms) <= sla.MIN_VMS:
            print(f"\n  [SKIP] Only {len(current_vms)} VM(s) — need more than MIN_VMS={sla.MIN_VMS} to scale down")
        else:
            sla.SCALE_DOWN_CPU_PCT  = 200.0  # any CPU < 200% triggers scale down
            sla.SCALE_DOWN_WINDOW_SEC = 0    # no waiting — destroy immediately

            # Pre-populate idle timers so the window check passes instantly
            from datetime import datetime, timezone
            autoscale_vms = [v for v in current_vms if v["name"].startswith(AUTOSCALE_PREFIX)]
            for vm in autoscale_vms:
                _idle_since[vm["one_vm_id"]] = datetime.now(timezone.utc)

            print(f"\n  SCALE_DOWN_CPU_PCT overridden to {sla.SCALE_DOWN_CPU_PCT}")
            print(f"  SCALE_DOWN_WINDOW_SEC overridden to {sla.SCALE_DOWN_WINDOW_SEC}")
            print("  Calling autoscaler check...")

            scaler._check_and_scale()
            print_vms("VMs immediately after check")

            total_before = len(list_all_vms())
            print("\n  Waiting for VM to be removed (up to 30s)...")
            if wait_for_vm_count(total_before - 1, timeout=30):
                print("  [OK] VM was destroyed")
            else:
                print("  [WARN] VM may still be terminating")
            print_vms("VMs after scale down")

        # ── Final state ───────────────────────────────────────────────────────
        separator("STEP 4 — Final state")
        print_vms("VMs in OpenNebula")

    finally:
        # Always restore original SLA values
        sla.SCALE_UP_CPU_PCT      = original_scale_up
        sla.SCALE_DOWN_CPU_PCT    = original_scale_down
        sla.SCALE_DOWN_WINDOW_SEC = original_window
        _idle_since.clear()
        print(f"\n  SLA values restored to originals.")
        print(f"    SCALE_UP_CPU_PCT      = {sla.SCALE_UP_CPU_PCT}")
        print(f"    SCALE_DOWN_CPU_PCT    = {sla.SCALE_DOWN_CPU_PCT}")
        print(f"    SCALE_DOWN_WINDOW_SEC = {sla.SCALE_DOWN_WINDOW_SEC}\n")
