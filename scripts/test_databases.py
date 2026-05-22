import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token

BASE_URL = "http://localhost:8000"

def test_database_lifecycle():
    print("=" * 50)
    print("Testing Remote Database Service via FastAPI API...")
    print("=" * 50)

    # 1. Generate JWT Token for user 'angie' (user_id = 3)
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"[OK] Generated access token for 'angie'.")

    # 2. List databases initially
    print("\nListing existing databases:")
    r = requests.get(f"{BASE_URL}/databases", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] List databases failed: {r.status_code} - {r.text}")
        return
    initial_dbs = r.json()
    print(f"Found {len(initial_dbs)} databases:")
    for db in initial_dbs:
        print(f"  - [{db['id']}] {db['instance_name']} (status={db['status']})")

    # 3. Provision a database
    db_name = "testdb"
    provision_payload = {
        "name": "mytestdb",
        "db_name": db_name
    }
    print(f"\nProvisioning new database 'mytestdb' (db_name={db_name})...")
    r = requests.post(f"{BASE_URL}/databases", json=provision_payload, headers=headers)
    if r.status_code != 201:
        print(f"[FAIL] Provision database failed: {r.status_code} - {r.text}")
        return
    db_info = r.json()
    db_id = db_info["id"]
    print(f"[OK] Provisioned: id={db_id}, name={db_info['instance_name']}, status={db_info['status']}")
    print(f"Credentials: {db_info['credentials']}")

    # 4. List databases again
    print("\nListing databases to verify addition:")
    r = requests.get(f"{BASE_URL}/databases", headers=headers)
    dbs = r.json()
    print(f"Found {len(dbs)} databases.")

    # 5. Get database detail
    print(f"\nGetting details for database {db_id}...")
    r = requests.get(f"{BASE_URL}/databases/{db_id}", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Get database details failed: {r.status_code} - {r.text}")
        return
    details = r.json()
    print(f"[OK] Details: status={details['status']}, host={details['credentials']['host']}, connection_string={details['credentials']['connection_string']}")

    # 6. Deprovision database
    print(f"\nDeprovisioning database {db_id}...")
    r = requests.delete(f"{BASE_URL}/databases/{db_id}", headers=headers)
    if r.status_code != 204:
        print(f"[FAIL] Deprovision database failed: {r.status_code} - {r.text}")
        return
    print(f"[OK] Database {db_id} deprovisioned.")

    # 7. Verify database list is back to initial state
    print("\nListing databases again to verify removal:")
    r = requests.get(f"{BASE_URL}/databases", headers=headers)
    final_dbs = r.json()
    print(f"Found {len(final_dbs)} databases.")
    print("\n" + "=" * 50)
    print("Database service verification complete!")
    print("=" * 50)

if __name__ == "__main__":
    try:
        test_database_lifecycle()
    except Exception as e:
        print(f"Error executing test: {e}")
