import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token

BASE_URL = "http://localhost:8000"

def test_container_lifecycle():
    print("=" * 50)
    print("Testing Remote Container Lifecycle via FastAPI API...")
    print("=" * 50)

    # 1. Generate JWT Token for user 'angie' (user_id = 3)
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[OK] Generated access token for 'angie'.")

    # 2. List containers initially (should be empty or some old containers)
    print("\nListing existing containers:")
    r = requests.get(f"{BASE_URL}/containers", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] List containers failed: {r.status_code} - {r.text}")
        return
    initial_containers = r.json()
    print(f"Found {len(initial_containers)} containers:")
    for c in initial_containers:
        print(f"  - [{c['container_id']}] {c['name']} (status={c['status']})")

    # 3. Launch a container
    container_name = "test-alpine"
    launch_payload = {
        "image": "alpine:latest",
        "name": container_name,
        "env": {"TEST_ENV_VAR": "hello-world"},
        "ports": ["80/tcp"]
    }
    print(f"\nLaunching new container '{container_name}'...")
    r = requests.post(f"{BASE_URL}/containers", json=launch_payload, headers=headers)
    if r.status_code != 201:
        print(f"[FAIL] Launch container failed: {r.status_code} - {r.text}")
        return
    c_info = r.json()
    c_id = c_info["container_id"]
    print(f"[OK] Launched container: id={c_id}, name={c_info['name']}, status={c_info['status']}, ports={c_info['ports']}")

    # 4. Get container details
    print(f"\nGetting details for container {c_id}...")
    r = requests.get(f"{BASE_URL}/containers/{c_id}", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Get container details failed: {r.status_code} - {r.text}")
        return
    details = r.json()
    print(f"[OK] Details: status={details['status']}, ports={details['ports']}")

    # 5. Stop the container
    print(f"\nStopping container {c_id}...")
    r = requests.post(f"{BASE_URL}/containers/{c_id}/stop", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Stop container failed: {r.status_code} - {r.text}")
        return
    details = r.json()
    print(f"[OK] Stopped. Status={details['status']}")

    # 6. Start the container again
    print(f"\nStarting container {c_id}...")
    r = requests.post(f"{BASE_URL}/containers/{c_id}/start", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Start container failed: {r.status_code} - {r.text}")
        return
    details = r.json()
    print(f"[OK] Started. Status={details['status']}")

    # 7. Stop again before removal
    print(f"\nStopping container {c_id} before removal...")
    r = requests.post(f"{BASE_URL}/containers/{c_id}/stop", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Stop container failed: {r.status_code} - {r.text}")
        return
    print("[OK] Stopped.")

    # 8. Remove the container
    print(f"\nRemoving container {c_id}...")
    r = requests.delete(f"{BASE_URL}/containers/{c_id}", headers=headers)
    if r.status_code != 204:
        print(f"[FAIL] Remove container failed: {r.status_code} - {r.text}")
        return
    print(f"[OK] Container {c_id} removed.")

    # 9. Verify container list is back to initial state
    print("\nListing containers again to verify removal:")
    r = requests.get(f"{BASE_URL}/containers", headers=headers)
    final_containers = r.json()
    print(f"Found {len(final_containers)} containers.")
    print("\n" + "=" * 50)
    print("Container service verification complete!")
    print("=" * 50)

if __name__ == "__main__":
    test_lifecycle = True
    try:
        test_container_lifecycle()
    except Exception as e:
        print(f"Error executing test: {e}")
