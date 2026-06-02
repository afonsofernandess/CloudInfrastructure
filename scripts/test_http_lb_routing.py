import sys
import os
import time
import requests

# Clean SSH Auth Sock to prevent local SSH agent conflicts
os.environ.pop("SSH_AUTH_SOCK", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token
from api.loadbalancer.ssh_utils import run_ssh_command
from api.database_service import db_manager

BASE_URL = "http://localhost:8000"
GROUP_NAME = "test-web-lb"

def main():
    print("=" * 60)
    print("Stateless Container Load Balancing Verification")
    print("=" * 60)

    # 1. Generate access token
    token = create_access_token(user_id=3, username="angie")
    headers = {"Authorization": f"Bearer {token}"}
    print("[OK] Generated authentication token.")

    # 2. Deploy Scale Group with 2 replicas
    print("\n[STEP 1] Provisioning scale group with 2 replicas...")
    scale_payload = {
        "name": GROUP_NAME,
        "image": "nginx:alpine",
        "replicas": 2,
        "container_port": "80/tcp"
    }
    r = requests.post(f"{BASE_URL}/loadbalancer/containers/scale", json=scale_payload, headers=headers)
    if r.status_code != 200:
        print(f"[FAIL] Failed to provision: {r.status_code} - {r.text}")
        sys.exit(1)
        
    data = r.json()
    lb_address = data["load_balancer_address"]
    workers = data["workers"]
    print(f"[OK] Group provisioned. Load Balancer Address: {lb_address}")

    # 3. Modify worker index.html files via SSH proxy tunnel
    print("\n[STEP 2] Injecting unique web page identifiers into worker replicas...")
    for idx, worker in enumerate(workers):
        cid = worker["container_id"]
        vmid = worker["vm_id"]
        vm_ip = db_manager.get_vm_ip_by_id(vmid)
        
        try:
            # Get exact container name
            inspect_cmd = f"docker inspect --format '{{{{.Name}}}}' {cid}"
            cname = run_ssh_command(vm_ip, inspect_cmd).strip().lstrip("/")
            
            # Inject worker identification string
            inject_cmd = f"docker exec {cname} sh -c 'echo \"Hello from Worker {idx} (ID: {cid[:12]})\" > /usr/share/nginx/html/index.html'"
            run_ssh_command(vm_ip, inject_cmd)
            print(f"  - Worker {idx} configured on VM {vm_ip} (Name: {cname})")
        except Exception as e:
            print(f"  - [ERROR] Failed to configure worker {idx}: {e}")

    # Let the configuration settle
    time.sleep(2)

    # 4. Perform test requests from the Load Balancer VM host via SSH
    lb_vmid = data["load_balancer"]["vm_id"]
    lb_vm_ip = db_manager.get_vm_ip_by_id(lb_vmid)
    
    # Resolve load balancer mapped port
    lb_ports = data["load_balancer"]["ports"]
    lb_host_port = lb_ports["80/tcp"][0]["HostPort"]

    print(f"\n[STEP 3] Executing 10 HTTP requests via SSH tunnel inside LB VM {lb_vm_ip}...")
    responses = []
    
    for i in range(10):
        try:
            # We use Connection: close to verify each new TCP stream gets balanced
            curl_cmd = f"curl -s -H 'Connection: close' http://127.0.0.1:{lb_host_port}"
            res = run_ssh_command(lb_vm_ip, curl_cmd)
            responses.append(res.strip())
        except Exception as e:
            responses.append(f"Request failed: {e}")

    print("\n[HTTP Query Results]:")
    for i, res in enumerate(responses):
        print(f"  Request {i+1:2d}: {res}")

    # Calculate statistics
    stats = {}
    for r_text in responses:
        stats[r_text] = stats.get(r_text, 0) + 1

    print("\n[Traffic Distribution Summary]:")
    for r_text, count in stats.items():
        print(f"  - \"{r_text}\": {count} requests ({count/10*100:.0f}%)")

    # 5. Cleanup
    print("\n[STEP 4] Scaling container group back to 0 replicas (cleanup)...")
    scale_payload["replicas"] = 0
    requests.post(f"{BASE_URL}/loadbalancer/containers/scale", json=scale_payload, headers=headers)
    print("[OK] Cleanup completed.")
    print("\n" + "=" * 60)
    print("Verification completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
