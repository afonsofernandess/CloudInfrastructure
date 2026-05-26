import sys
import os
import time
from datetime import datetime, timezone, timedelta

# Setup python path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import SessionLocal
from api.auth.models import User
from api.compute.models import VMInstance
from api.compute import sla
from api.compute.autoscaler import AutoScaler
from opennebula.vm_manager import get_vm, list_all_vms
from api.containers.docker_client import ensure_user_has_running_vm


def separator(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def run_test():
    db = SessionLocal()
    user = db.query(User).filter(User.username == "angie").first()
    if not user:
        print("[FAIL] User 'angie' does not exist in local database. Please register/create a user first.")
        db.close()
        return
    db.close()

    # Save original inactivity timeout
    original_timeout = sla.USER_INACTIVITY_TIMEOUT_SEC
    original_min_vms = sla.MIN_VMS

    try:
        # ──────────────────────────────────────────────────────────────────────
        # STEP 1: Verify on-demand VM booting/creation
        # ──────────────────────────────────────────────────────────────────────
        separator("STEP 1: Verify on-demand VM booting / creation")
        print("Ensuring user 'angie' has a running VM (this will auto-create or resume one)...")
        
        vm_id = ensure_user_has_running_vm("angie")
        print(f"[OK] ensure_user_has_running_vm returned VM ID: {vm_id}")

        # Query OpenNebula to verify it is active and running
        db = SessionLocal()
        vm_inst = db.query(VMInstance).filter(VMInstance.id == vm_id).first()
        one_vm_id = vm_inst.one_vm_id
        db.close()

        live = get_vm(one_vm_id)
        print(f"VM state in OpenNebula: Name={live['name']}, State={live['state']}, LCM={live['lcm_state']}, IP={live['ip_address']}")
        
        if not (live["state"] == "ACTIVE" and live["lcm_state"] == 3):
            print("[FAIL] VM is not in ACTIVE / RUNNING state.")
            return

        # ──────────────────────────────────────────────────────────────────────
        # STEP 2: Verify user inactivity VM suspension
        # ──────────────────────────────────────────────────────────────────────
        separator("STEP 2: Verify user inactivity VM suspension")
        print("Overriding inactivity timeout to 5 seconds...")
        sla.USER_INACTIVITY_TIMEOUT_SEC = 5
        sla.MIN_VMS = 0

        # Simulate inactivity by pushing last_active_at to 10 seconds ago
        db = SessionLocal()
        user = db.query(User).filter(User.username == "angie").first()
        user.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()
        print(f"Simulating user inactivity. last_active_at set to: {user.last_active_at}")
        db.close()

        print("Running autoscaler loop to detect inactivity...")
        scaler = AutoScaler()
        scaler._check_and_scale()

        print("Waiting for VM to transition to SUSPENDED or POWEROFF state (polling up to 60s)...")
        suspended = False
        for i in range(30):
            live = get_vm(one_vm_id)
            print(f"  Poll {i+1}: VM State={live['state']}")
            if live["state"] in ("SUSPENDED", "POWEROFF"):
                suspended = True
                print(f"[OK] Success! VM '{live['name']}' was automatically suspended due to inactivity.")
                break
            time.sleep(2)

        if not suspended:
            print("[FAIL] VM was not suspended.")
            return

        # ──────────────────────────────────────────────────────────────────────
        # STEP 3: Verify user activity VM resumption
        # ──────────────────────────────────────────────────────────────────────
        separator("STEP 3: Verify user activity VM resumption")
        print("Simulating user activity by updating last_active_at to current time...")
        
        db = SessionLocal()
        user = db.query(User).filter(User.username == "angie").first()
        user.last_active_at = datetime.now(timezone.utc)
        db.commit()
        db.close()

        print("Running autoscaler loop to detect activity...")
        scaler._check_and_scale()

        print("Waiting for VM to transition back to ACTIVE state (polling up to 60s)...")
        resumed = False
        for i in range(30):
            live = get_vm(one_vm_id)
            print(f"  Poll {i+1}: VM State={live['state']}, LCM={live['lcm_state']}")
            if live["state"] == "ACTIVE":
                resumed = True
                print(f"[OK] Success! VM '{live['name']}' was automatically resumed.")
                break
            time.sleep(2)

        if not resumed:
            print("[FAIL] VM failed to resume.")
            return

        # Wait for LCM_STATE to be RUNNING (3) again to leave the VM in a clean state
        print("Waiting for VM to be fully RUNNING again...")
        for i in range(30):
            live = get_vm(one_vm_id)
            if live["lcm_state"] == 3:
                print("[OK] VM is fully booted and ready.")
                break
            time.sleep(2)

        separator("TEST SUMMARY: ALL PASSED!")
        print("1. [PASS] On-demand VM provisioning/booting works.")
        print("2. [PASS] Inactive user VMs automatically suspend to save energy.")
        print("3. [PASS] Active user VMs automatically resume.")

    finally:
        # Restore SLA settings
        sla.USER_INACTIVITY_TIMEOUT_SEC = original_timeout
        sla.MIN_VMS = original_min_vms
        print("\nSLA thresholds successfully restored.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\n[ERROR] Test run failed: {e}")
