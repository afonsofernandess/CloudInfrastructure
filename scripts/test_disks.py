import sys
import os
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_URL = "http://localhost:8000"

def get_token():
    # Login as testuser
    payload = {"username": "testuser", "password": "secret123"}
    r = requests.post(f"{API_URL}/auth/login", json=payload)
    if r.status_code == 200:
        return r.json()["access_token"]
    
    # Try register if login fails
    reg_payload = {"username": "testuser", "email": "test@cloud.com", "password": "secret123"}
    r = requests.post(f"{API_URL}/auth/register", json=reg_payload)
    if r.status_code == 201:
        # Login again
        r = requests.post(f"{API_URL}/auth/login", json=payload)
        return r.json()["access_token"]
        
    raise Exception(f"Failed to get token: {r.text}")


def test_disk_lifecycle():
    print("=" * 50)
    print("Testing Disk Management (Block Storage) API...")
    print("=" * 50)
    
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Provision a disk
    disk_name = f"test-disk-{int(time.time())}"
    print(f"\n[1/4] Provisioning a custom 1GB disk: {disk_name}...")
    r = requests.post(
        f"{API_URL}/storage/disks",
        json={"name": disk_name, "size_gb": 1},
        headers=headers
    )
    if r.status_code != 201:
        print(f"[FAIL] Failed to create disk: {r.text}")
        sys.exit(1)
        
    disk = r.json()
    disk_id = disk["id"]
    print(f"[OK] Disk provisioned! local_id: {disk_id}, one_image_id: {disk['one_image_id']}, status: {disk['status']}")
    
    # 2. List disks
    print("\n[2/4] Listing user disks...")
    r = requests.get(f"{API_URL}/storage/disks", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Failed to list disks: {r.text}")
        sys.exit(1)
        
    disks = r.json()
    found = False
    for d in disks:
        print(f"  - Disk [{d['id']}] {d['name']} ({d['size_gb']} GB) - Status: {d['status']}")
        if d["id"] == disk_id:
            found = True
            
    if not found:
        print("[FAIL] Provisioned disk not found in the list!")
        sys.exit(1)
    print("[OK] Disk found in user disk list.")
    
    # 3. Wait for READY state
    print("\n[3/4] Waiting for disk to become READY in OpenNebula...")
    max_retries = 20
    for i in range(max_retries):
        r = requests.get(f"{API_URL}/storage/disks", headers=headers)
        disks = r.json()
        current_status = None
        for d in disks:
            if d["id"] == disk_id:
                current_status = d["status"]
                break
                
        print(f"  Check {i+1}: status is '{current_status}'")
        if current_status == "READY":
            print("[OK] Disk is READY!")
            break
        elif current_status == "ERROR":
            print("[FAIL] Disk entered ERROR state!")
            sys.exit(1)
        time.sleep(1.5)
    else:
        print("[WARNING] Timeout waiting for disk to become READY. Proceeding with cleanup...")

    # 4. Delete disk
    print(f"\n[4/4] Deleting disk {disk_id}...")
    r = requests.delete(f"{API_URL}/storage/disks/{disk_id}", headers=headers)
    if r.status_code == 400 and "locked" in r.json().get("detail", "").lower():
        # wait a bit more and retry once
        print("  Disk locked, waiting 3 seconds before retry...")
        time.sleep(3)
        r = requests.delete(f"{API_URL}/storage/disks/{disk_id}", headers=headers)
        
    if r.status_code != 204:
        print(f"[FAIL] Failed to delete disk: {r.text}")
        sys.exit(1)
    print("[OK] Disk successfully deleted!")
    
    print("\n" + "=" * 50)
    print("Disk Management API test complete.")
    print("=" * 50)

if __name__ == "__main__":
    # Make sure backend is running first
    try:
        requests.get(API_URL)
    except requests.exceptions.ConnectionError:
        print("[ERROR] FastAPI backend is not running. Please start it on port 8000 first!")
        sys.exit(1)
        
    test_disk_lifecycle()
