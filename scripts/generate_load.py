import sys
import os
import requests
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token
from api.loadbalancer.ssh_utils import run_ssh_command

BASE_URL = "http://localhost:8000"
GROUP_NAME = "nginx_hello"

def get_auth_headers():
    token = create_access_token(user_id=3, username="angie")
    return {"Authorization": f"Bearer {token}"}

def main():
    parser = argparse.ArgumentParser(description="Simulate container CPU load for testing autoscaling.")
    parser.add_argument("action", choices=["start", "stop"], help="Start or stop CPU load simulation.")
    args = parser.parse_args()
    
    headers = get_auth_headers()
    r = requests.get(f"{BASE_URL}/loadbalancer/containers/scale/{GROUP_NAME}", headers=headers)
    if r.status_code != 200:
        print(f"Error fetching group details: {r.status_code} - {r.text}")
        sys.exit(1)
        
    data = r.json()
    workers = data.get("workers", [])
    if not workers:
        print(f"No active workers found in group '{GROUP_NAME}'. Please provision the container group first.")
        sys.exit(1)
        
    from api.database import SessionLocal
    from api.database_service import db_manager

    if args.action == "start":
        worker = workers[0]
        container_id = worker["container_id"]
        vm_id = worker["vm_id"]
        vm_ip = db_manager.get_vm_ip_by_id(vm_id)

        container_name_cmd = f"docker inspect --format '{{{{.Name}}}}' {container_id}"
        container_name = run_ssh_command(vm_ip, container_name_cmd).strip().lstrip("/")

        print(f"Starting CPU load simulation inside container '{container_name}' on VM IP {vm_ip}...")
        stress_cmd = f"docker exec -d {container_name} sh -c 'sha256sum /dev/zero'"
        run_ssh_command(vm_ip, stress_cmd)
        print("[OK] CPU load started! Check the autoscale watchdog for scale up.")
    else:
        print("Stopping CPU load simulation inside all container workers...")
        for w in workers:
            cid = w["container_id"]
            vmid = w["vm_id"]
            vm_ip = db_manager.get_vm_ip_by_id(vmid)

            container_name_cmd = f"docker inspect --format '{{{{.Name}}}}' {cid}"
            cname = run_ssh_command(vm_ip, container_name_cmd).strip().lstrip("/")

            print(f"  - Stopping load in '{cname}' on VM {vm_ip}...")
            stop_cmd = f"docker exec {cname} killall sha256sum || true"
            run_ssh_command(vm_ip, stop_cmd)
        print("[OK] CPU load stopped on all workers! Check the autoscale watchdog for scale down.")

if __name__ == "__main__":
    main()
