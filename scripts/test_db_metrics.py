import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token

BASE_URL = "http://localhost:8000"

def test_db_metrics():
    print("=" * 50)
    print("Testing Database Metrics Endpoint via FastAPI...")
    print("=" * 50)

    # 1. Generate JWT Token for user 'angie'
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print("[OK] Generated access token.")

    # 2. Get list of databases to find an active one
    print("\nFetching user's databases...")
    r = requests.get(f"{BASE_URL}/databases", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Fetching databases failed: {r.status_code} - {r.text}")
        return
    dbs = r.json()
    if not dbs:
        print("[INFO] No databases running. Provisioning one first...")
        provision_payload = {
            "name": "metricstest",
            "db_name": "testmetrics"
        }
        r = requests.post(f"{BASE_URL}/databases", json=provision_payload, headers=headers)
        if r.status_code != 201:
            print(f"[FAIL] Failed to provision database: {r.text}")
            return
        db_info = r.json()
        db_id = db_info["id"]
        temp_created = True
    else:
        db_info = dbs[0]
        db_id = db_info["id"]
        temp_created = False
        print(f"[OK] Found existing database: id={db_id}, name={db_info['instance_name']}")

    # 3. Query the metrics endpoint
    print(f"\nQuerying metrics for database ID {db_id}...")
    r = requests.get(f"{BASE_URL}/databases/{db_id}/metrics", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Metrics retrieval failed: {r.status_code} - {r.text}")
    else:
        metrics = r.json()
        print(f"[SUCCESS] Metrics returned successfully:")
        print(f"  - Active Connections: {metrics.get('active_connections')}")
        print(f"  - Database Size: {metrics.get('db_size')}")
        print(f"  - Timestamp: {metrics.get('timestamp')}")
        if metrics.get('error'):
            print(f"  - Warning/Error: {metrics['error']}")

    # 4. Clean up if we created a temporary database
    if temp_created:
        print(f"\nDeprovisioning temporary database {db_id}...")
        r = requests.delete(f"{BASE_URL}/databases/{db_id}", headers=headers)
        if r.status_code == 204:
            print("[OK] Temporary database removed.")
        else:
            print(f"[FAIL] Cleanup failed: {r.text}")

    print("\n" + "=" * 50)
    print("Database metrics verification complete!")
    print("=" * 50)

if __name__ == "__main__":
    test_db_metrics()
