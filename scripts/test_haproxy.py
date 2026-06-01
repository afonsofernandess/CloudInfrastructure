import sys
import os
import time
import requests
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token
from api.loadbalancer.ssh_utils import run_ssh_command

BASE_URL = "http://localhost:8000"

def run_haproxy_test():
    print("=" * 60)
    print("Testing HAProxy Load Balancing & Replication via SSH tunnels...")
    print("=" * 60)

    # 1. Generate access token
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print("[OK] Generated token.")

    # 2. Fetch cluster details
    print("Fetching 'test-db-lb' cluster details...")
    r = requests.get(f"{BASE_URL}/loadbalancer/databases/cluster/test-db-lb", headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Could not fetch cluster details: {r.status_code} - {r.text}")
        sys.exit(1)
        
    cluster = r.json()
    primary = cluster.get("primary")
    replicas = cluster.get("replicas")
    lb = cluster.get("load_balancer")
    
    if not primary or not lb or not replicas:
        print("[FAIL] Missing cluster components. Ensure test-db-lb exists and has replicas.")
        sys.exit(1)
        
    # Extract credentials and host/ports
    db_name = primary["credentials"]["db_name"]
    db_user = primary["credentials"]["db_user"]
    db_password = primary["credentials"]["db_password"]
    
    primary_container = f"db-angie-test-db-lb-primary"
    primary_vm_ip = primary["credentials"]["host"]
    
    lb_ip = lb["credentials"]["host"]
    lb_write_port = lb["credentials"]["port"]
    lb_read_port = lb["read_host_port"]
    
    print("\nCluster Info:")
    print(f"  - Primary VM IP: {primary_vm_ip}")
    print(f"  - HAProxy VM IP: {lb_ip}")
    print(f"  - HAProxy Write Port (Host): {lb_write_port}")
    print(f"  - HAProxy Read Port (Host):  {lb_read_port}")
    print(f"  - Database Name: {db_name}")
    print(f"  - Database User: {db_user}")
    
    # 3. Create Test Table & Write via HAProxy Write Port (5432 on container, lb_write_port on VM)
    print("\n[STEP 1] Writing test data via HAProxy Write Port...")
    write_sql = (
        "CREATE TABLE IF NOT EXISTS haproxy_test (id serial PRIMARY KEY, val text); "
        "TRUNCATE TABLE haproxy_test; "
        "INSERT INTO haproxy_test (val) VALUES ('HAProxy Replication Verification');"
    )
    
    # Run the query inside the primary container pointing at HAProxy's IP and write port
    write_cmd = (
        f"docker exec -e PGPASSWORD='{db_password}' {primary_container} psql "
        f"-h {lb_ip} -p {lb_write_port} -U {db_user} -d {db_name} -c \"{write_sql}\""
    )
    
    try:
        run_ssh_command(primary_vm_ip, write_cmd)
        print("[OK] Test table created and record inserted via HAProxy write port.")
    except Exception as e:
        print(f"[FAIL] Write query through HAProxy failed: {e}")
        sys.exit(1)

    # Allow a moment for WAL streaming to update replicas
    print("Waiting 2 seconds for replication to propagate...")
    time.sleep(2)

    # 4. Verify replication on each replica directly
    print("\n[STEP 2] Verifying replica synchronization directly...")
    for idx, replica in enumerate(replicas):
        replica_container = f"db-angie-test-db-lb-replica-{idx+1}"
        replica_vm_ip = replica["credentials"]["host"]
        read_replica_cmd = (
            f"docker exec -e PGPASSWORD='{db_password}' {replica_container} psql "
            f"-U {db_user} -d {db_name} -t -A -c \"SELECT val FROM haproxy_test LIMIT 1;\""
        )
        try:
            val = run_ssh_command(replica_vm_ip, read_replica_cmd).strip()
            if val == "HAProxy Replication Verification":
                print(f"[OK] Replica #{idx+1} ({replica_vm_ip}) has correct replicated data.")
            else:
                print(f"[FAIL] Replica #{idx+1} has unexpected data: '{val}'")
        except Exception as e:
            print(f"[FAIL] Direct read query from Replica #{idx+1} failed: {e}")

    # 5. Test Round-Robin Load Balancing on Read Port (5433 on container, lb_read_port on VM)
    print("\n[STEP 3] Testing HAProxy Read Port load balancing (round-robin)...")
    read_lb_cmd = (
        f"docker exec -e PGPASSWORD='{db_password}' {primary_container} psql "
        f"-h {lb_ip} -p {lb_read_port} -U {db_user} -d {db_name} -t -A -c \"SELECT inet_server_addr();\""
    )
    
    server_ips = []
    # Query 5 times to see multiple backends responding
    for i in range(5):
        try:
            ip = run_ssh_command(primary_vm_ip, read_lb_cmd).strip()
            server_ips.append(ip)
            print(f"  - Query #{i+1} handled by backend container IP: {ip}")
        except Exception as e:
            print(f"[FAIL] Read query #{i+1} through HAProxy failed: {e}")
            
    unique_backends = set(server_ips)
    print(f"\nSummary of responding backend database IPs: {list(unique_backends)}")
    if len(unique_backends) > 1:
        print("[OK] Round-robin load balancing via HAProxy is WORKING!")
    else:
        print("[FAIL] All read queries went to the same backend. Check HAProxy configuration.")
        
    print("=" * 60)
    print("HAProxy Load Balancing & Replication verification completed!")
    print("=" * 60)

if __name__ == "__main__":
    run_haproxy_test()
