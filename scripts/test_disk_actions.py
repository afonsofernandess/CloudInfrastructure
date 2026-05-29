import sys
import os
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_URL = "http://localhost:8000"

def get_token():
    payload = {"username": "testuser", "password": "secret123"}
    r = requests.post(f"{API_URL}/auth/login", json=payload)
    if r.status_code == 200:
        return r.json()["access_token"]
    raise Exception("Please create 'testuser' with 'secret123' first.")


def test_attach_detach():
    print("=" * 50)
    print("Testing Disk Attach / Detach API Lifecycle...")
    print("=" * 50)
    
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get active VM ID
    print("\n[1/5] Fetching user's active VMs...")
    r = requests.get(f"{API_URL}/compute/vms", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Could not list VMs: {r.text}")
        sys.exit(1)
        
    vms = [vm for vm in r.json() if vm["state"] == "ACTIVE"]
    if not vms:
        print("[FAIL] No active VMs found! Please provision a VM first.")
        sys.exit(1)
        
    target_vm = vms[0]
    print(f"[OK] Found active VM: {target_vm['name']} (local_id: {target_vm['id']}, one_vm_id: {target_vm['one_vm_id']})")
    
    # Provision a disk
    disk_name = f"attach-test-{int(time.time())}"
    print(f"\n[2/5] Creating 1GB block storage disk: {disk_name}...")
    r = requests.post(
        f"{API_URL}/storage/disks",
        json={"name": disk_name, "size_gb": 1},
        headers=headers
    )
    if r.status_code != 201:
        print(f"[FAIL] Could not create disk: {r.text}")
        sys.exit(1)
        
    disk = r.json()
    disk_id = disk["id"]
    print(f"[OK] Disk created: {disk['name']} (local_id: {disk_id})")
    
    # Wait for disk to be READY
    print("Waiting for disk to become READY in OpenNebula...")
    for _ in range(15):
        r = requests.get(f"{API_URL}/storage/disks", headers=headers)
        disks = r.json()
        status = next((d["status"] for d in disks if d["id"] == disk_id), None)
        if status == "READY":
            print("[OK] Disk is READY.")
            break
        time.sleep(1.5)
    else:
        print("[FAIL] Timeout waiting for disk to be READY.")
        sys.exit(1)
        
    # Attach disk to VM
    print(f"\n[3/5] Attaching disk {disk_id} to VM {target_vm['id']}...")
    r = requests.post(
        f"{API_URL}/storage/disks/{disk_id}/attach",
        json={"vm_id": target_vm["id"]},
        headers=headers
    )
    if r.status_code != 204:
        print(f"[FAIL] Attach endpoint failed: {r.text}")
        sys.exit(1)
    print("[OK] Attach request accepted.")
    
    # Verify it is listed as attached
    print("Waiting 5 seconds and checking disk listing...")
    time.sleep(5)
    r = requests.get(f"{API_URL}/storage/disks", headers=headers)
    disks = r.json()
    updated_disk = next((d for d in disks if d["id"] == disk_id), None)
    if updated_disk and updated_disk["attached_vm_id"] == target_vm["id"]:
        print(f"[OK] Verified! Disk is listed as attached to '{updated_disk['attached_vm_name']}'")
    else:
        print(f"[FAIL] Disk is NOT listed as attached. Disk object: {updated_disk}")
        sys.exit(1)
        
    # Detach disk
    print(f"\n[4/5] Detaching disk {disk_id}...")
    r = requests.post(
        f"{API_URL}/storage/disks/{disk_id}/detach",
        headers=headers
    )
    if r.status_code != 204:
        print(f"[FAIL] Detach endpoint failed: {r.text}")
        sys.exit(1)
    print("[OK] Detach request accepted.")
    
    # Verify it is listed as unattached
    print("Waiting 5 seconds and checking disk listing...")
    time.sleep(5)
    r = requests.get(f"{API_URL}/storage/disks", headers=headers)
    disks = r.json()
    updated_disk = next((d for d in disks if d["id"] == disk_id), None)
    if updated_disk and updated_disk["attached_vm_id"] is None:
        print("[OK] Verified! Disk is listed as unattached.")
    else:
        print(f"[FAIL] Disk is still listed as attached to VM {updated_disk.get('attached_vm_id')}")
        sys.exit(1)
        
    # Delete the disk
    print(f"\n[5/5] Deleting the disk {disk_id}...")
    r = requests.delete(f"{API_URL}/storage/disks/{disk_id}", headers=headers)
    if r.status_code != 204:
        print(f"[FAIL] Could not delete disk: {r.text}")
        sys.exit(1)
    print("[OK] Disk deleted.")
    
    print("\n" + "=" * 50)
    print("Attach/Detach lifecycle verification test passed!")
    print("=" * 50)


if __name__ == "__main__":
    try:
        requests.get(API_URL)
    except requests.exceptions.ConnectionError:
        print("[ERROR] FastAPI backend is not running. Please start it on port 8000 first!")
        sys.exit(1)
    test_attach_detach()
