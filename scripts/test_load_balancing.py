import sys
import os
os.environ.pop("SSH_AUTH_SOCK", None)
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token

BASE_URL = "http://localhost:8000"


def run_tests():
    print("=" * 60)
    print("Testing Load Balancing and Replication via FastAPI...")
    print("=" * 60)

    # 1. Generate access token
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print("[OK] Generated token.")

    # 2. Test Container Scaling and Load Balancing
    print("\n[STEP 1] Testing Container Scaling & Nginx Load Balancing")
    scale_payload = {
        "name": "test-web-lb",
        "image": "nginx:alpine",
        "replicas": 2,
        "container_port": "80/tcp",
        "env": {"APP_VERSION": "1.0"}
    }
    
    print("Triggering scale-up of container group 'test-web-lb' to 2 replicas...")
    r = requests.post(f"{BASE_URL}/loadbalancer/containers/scale", json=scale_payload, headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Scale up failed: {r.status_code} - {r.text}")
    else:
        info = r.json()
        print(f"[OK] Scale group created successfully!")
        print(f"  - Group Name: {info['scale_group']}")
        print(f"  - Replicas Count: {info['replicas_count']}")
        print(f"  - Load Balancer Address: {info['load_balancer_address']}")
        print(f"  - Workers list:")
        for w in info["workers"]:
            print(f"    * [{w['container_id']}] {w['name']} status={w['status']} VM={w['vm_id']}")
        
        # Verify fetching scale group details
        print("\nRetrieving container group details via GET...")
        r_get = requests.get(f"{BASE_URL}/loadbalancer/containers/scale/test-web-lb", headers=headers)
        if r_get.status_code == 200:
            print("[OK] Retrieve scale details successful.")
        else:
            print(f"[FAIL] Retrieve details failed: {r_get.status_code}")

        # Scale down to 0 to clean up
        print("\nScaling down container group to 0 replicas (cleanup)...")
        scale_payload["replicas"] = 0
        r_cleanup = requests.post(f"{BASE_URL}/loadbalancer/containers/scale", json=scale_payload, headers=headers)
        if r_cleanup.status_code == 200:
            print("[OK] Cleaned up container group successfully.")
        else:
            print("[FAIL] Failed to clean up container group.")

    # 3. Test Database Cluster and Replication
    print("\n[STEP 2] Testing Database Cluster & HAProxy Load Balancing")
    db_payload = {
        "cluster_name": "test-db-lb",
        "db_name": "testdb",
        "replicas": 1
    }
    
    print("Triggering database cluster creation 'test-db-lb' (1 primary + 1 replica + 1 HAProxy)...")
    r_db = requests.post(f"{BASE_URL}/loadbalancer/databases/cluster", json=db_payload, headers=headers)
    if r_db.status_code != 201:
        print(f"[FAIL] DB Cluster creation failed: {r_db.status_code} - {r_db.text}")
    else:
        info = r_db.json()
        print(f"[OK] DB Cluster created successfully!")
        print(f"  - Cluster: {info['cluster_name']}")
        print(f"  - Primary Host: {info['primary']['credentials']['host']}:{info['primary']['credentials']['port']} VM={info['primary']['vm_id']}")
        print(f"  - Replicas list:")
        for r_item in info["replicas"]:
            print(f"    * {r_item['credentials']['host']}:{r_item['credentials']['port']} Role={r_item['role']} VM={r_item['vm_id']}")
        print(f"  - Load Balancer: {info['load_balancer']['credentials']['host']}:{info['load_balancer']['credentials']['port']} (Read port: {info['load_balancer']['read_host_port']})")

        # Scale DB Cluster to 2 replicas
        print("\nScaling up DB Cluster to 2 replicas...")
        r_scale_db = requests.post(
            f"{BASE_URL}/loadbalancer/databases/cluster/test-db-lb/scale?replicas=2",
            headers=headers
        )
        if r_scale_db.status_code == 200:
            info_scaled = r_scale_db.json()
            print(f"[OK] Scaled up successfully! Total replicas: {len(info_scaled['replicas'])}")
        else:
            print(f"[FAIL] Scale up DB cluster failed: {r_scale_db.status_code} - {r_scale_db.text}")

        # Fetch DB Cluster details
        print("\nFetching DB Cluster details via GET...")
        r_get_db = requests.get(f"{BASE_URL}/loadbalancer/databases/cluster/test-db-lb", headers=headers)
        if r_get_db.status_code == 200:
            print("[OK] Fetch DB Cluster details successful.")
        else:
            print(f"[FAIL] Fetch DB Cluster details failed: {r_get_db.status_code}")

    print("\n" + "=" * 60)
    print("Load Balancing and Replication verification complete!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
