"""
Phase 1 - Test OpenNebula connection and basic operations.

HOW TO RUN:
    Make sure your SSH tunnel is active first:
        ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[ipaddress]

    Then run:
        python scripts/test_connection.py

WHAT TO EXPECT IF WORKING:
    - OpenNebula version printed
    - Current user info printed
    - List of existing VMs (can be empty)
    - List of available VM templates
    - List of available images/datastores
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opennebula.connection import get_client


def test_connection():
    print("=" * 50)
    print("Testing OpenNebula connection...")
    print("=" * 50)

    client = get_client()

    # 1. Check OpenNebula version
    try:
        version = client.system.version()
        print(f"\n[OK] Connected! OpenNebula version: {version}")
    except Exception as e:
        print(f"\n[FAIL] Could not connect: {e}")
        print("  -> Is your SSH tunnel running?")
        print("  -> Run: ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@192.168.1.177")
        sys.exit(1)

    # 2. Get current user info
    try:
        user_pool = client.userpool.info()
        print(f"\n[OK] Users in OpenNebula:")
        for user in user_pool.USER:
            print(f"  - [{user.ID}] {user.NAME}")
    except Exception as e:
        print(f"[FAIL] Could not fetch users: {e}")

    # 3. List running VMs
    try:
        vm_pool = client.vmpool.info(-2, -1, -1, -1)
        vms = vm_pool.VM if hasattr(vm_pool, "VM") else []
        print(f"\n[OK] Virtual Machines ({len(vms)} found):")
        if vms:
            for vm in vms:
                print(f"  - [{vm.ID}] {vm.NAME}  state={vm.STATE}")
        else:
            print("  (no VMs running)")
    except Exception as e:
        print(f"[FAIL] Could not fetch VMs: {e}")

    # 4. List VM templates
    try:
        template_pool = client.templatepool.info(-2, -1, -1)
        templates = template_pool.VMTEMPLATE if hasattr(template_pool, "VMTEMPLATE") else []
        print(f"\n[OK] VM Templates ({len(templates)} found):")
        if templates:
            for t in templates:
                print(f"  - [{t.ID}] {t.NAME}")
        else:
            print("  (no templates found)")
    except Exception as e:
        print(f"[FAIL] Could not fetch templates: {e}")

    # 5. List datastores
    try:
        ds_pool = client.datastorepool.info()
        datastores = ds_pool.DATASTORE if hasattr(ds_pool, "DATASTORE") else []
        print(f"\n[OK] Datastores ({len(datastores)} found):")
        for ds in datastores:
            print(f"  - [{ds.ID}] {ds.NAME}  type={ds.TYPE}")
    except Exception as e:
        print(f"[FAIL] Could not fetch datastores: {e}")

    # 6. List hosts (physical machines)
    try:
        host_pool = client.hostpool.info()
        hosts = host_pool.HOST if hasattr(host_pool, "HOST") else []
        print(f"\n[OK] Hosts / Physical machines ({len(hosts)} found):")
        for h in hosts:
            print(f"  - [{h.ID}] {h.NAME}  state={h.STATE}")
    except Exception as e:
        print(f"[FAIL] Could not fetch hosts: {e}")

    print("\n" + "=" * 50)
    print("Phase 1 connection test complete.")
    print("=" * 50)


if __name__ == "__main__":
    test_connection()
