"""
Quick diagnostic: what does container.stats(stream=False) actually return
on the worker VMs during the flood? Runs the flood in background and checks
the raw Docker stats values to find out why CPU reads as 0%.
"""
import sys, os, time, threading
os.environ.pop("SSH_AUTH_SOCK", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.loadbalancer.container_lb import scale_container_group, get_container_group_details
from api.loadbalancer.schemas import ContainerScaleRequest
from api.loadbalancer.ssh_utils import run_ssh_command
from api.containers.docker_client import get_client
from api.database_service import db_manager

USERNAME   = "angie"
GROUP_NAME = "autoscale-test"
IMAGE      = "nginx:alpine"
PORT       = "80/tcp"
PARALLEL   = 15
FLOOD_SECS = 40

def scale(replicas):
    req = ContainerScaleRequest(name=GROUP_NAME, image=IMAGE,
                                replicas=replicas, container_port=PORT, no_autoscale=True)
    return scale_container_group(USERNAME, req)

def main():
    print("=== CPU Stats Diagnostic ===")

    # Cleanup + provision
    print("\n[1] Cleanup + provision 2 workers (no_autoscale to prevent interference)...")
    try: scale(0)
    except: pass
    data = scale(2)
    workers = data.workers
    lb = data.load_balancer
    lb_vm_ip = db_manager.get_vm_ip_by_id(lb.vm_id)
    lb_host_port = lb.ports[PORT][0]["HostPort"]
    lb_url = f"http://127.0.0.1:{lb_host_port}/"
    print(f"  LB: {data.load_balancer_address}")
    for i, w in enumerate(workers):
        print(f"  Worker {i}: {w.container_id[:12]} on VM {db_manager.get_vm_ip_by_id(w.vm_id)}")

    # Wait for containers
    time.sleep(5)

    # Start flood in background
    print(f"\n[2] Starting {PARALLEL} concurrent curl loops for {FLOOD_SECS}s...")
    flood_cmd = (
        f"end=$(( $(date +%s) + {FLOOD_SECS} )); "
        f"for i in $(seq 1 {PARALLEL}); do "
        f"  ( while [ $(date +%s) -lt $end ]; do "
        f"      curl -s -o /dev/null {lb_url}; "
        f"    done ) & "
        f"done; wait"
    )
    flood_done = threading.Event()
    def run_flood():
        try: run_ssh_command(lb_vm_ip, flood_cmd, timeout=FLOOD_SECS + 20)
        except Exception as e: print(f"  flood error: {e}")
        finally: flood_done.set()
    threading.Thread(target=run_flood, daemon=True).start()

    # Wait 5s then take stats
    print("  Waiting 5s for flood to ramp up...")
    time.sleep(5)

    # For each worker, print raw stats
    for i, w in enumerate(workers):
        vm_ip = db_manager.get_vm_ip_by_id(w.vm_id)
        vm_id = w.vm_id
        print(f"\n[3] Worker {i} ({w.container_id[:12]} on {vm_ip}):")

        try:
            cli = get_client(USERNAME, vm_id)
            c = cli.containers.get(w.container_id)
            print(f"  Container status: {c.status}")

            print("  Taking s1 (stream=False)...")
            s1 = c.stats(stream=False)
            print("  Sleeping 1s...")
            time.sleep(1)
            print("  Taking s2 (stream=False)...")
            s2 = c.stats(stream=False)

            # Raw values
            cpu1     = s1.get("cpu_stats",    {}).get("cpu_usage",  {}).get("total_usage", "MISSING")
            cpu2     = s2.get("cpu_stats",    {}).get("cpu_usage",  {}).get("total_usage", "MISSING")
            pre1     = s1.get("precpu_stats", {}).get("cpu_usage",  {}).get("total_usage", "MISSING")
            pre2     = s2.get("precpu_stats", {}).get("cpu_usage",  {}).get("total_usage", "MISSING")
            sys1     = s1.get("cpu_stats",    {}).get("system_cpu_usage", "MISSING")
            sys2     = s2.get("cpu_stats",    {}).get("system_cpu_usage", "MISSING")
            cpus1    = s1.get("cpu_stats",    {}).get("online_cpus", "MISSING")
            cpus2    = s2.get("cpu_stats",    {}).get("online_cpus", "MISSING")

            print(f"  s1 cpu_stats.total_usage    : {cpu1}")
            print(f"  s2 cpu_stats.total_usage    : {cpu2}")
            print(f"  s1 precpu_stats.total_usage : {pre1}")
            print(f"  s2 precpu_stats.total_usage : {pre2}")
            print(f"  s1 system_cpu_usage         : {sys1}")
            print(f"  s2 system_cpu_usage         : {sys2}")
            print(f"  s1/s2 online_cpus           : {cpus1} / {cpus2}")

            # Calculate both ways
            if isinstance(cpu2, int) and isinstance(cpu1, int):
                delta_2sample = cpu2 - cpu1
                sys_delta_2sample = (s2.get("cpu_stats",{}).get("system_cpu_usage",0)
                                   - s1.get("cpu_stats",{}).get("system_cpu_usage",0))
                ncpus = cpus2 or 1
                pct_2sample = (delta_2sample / sys_delta_2sample * ncpus * 100.0
                               if sys_delta_2sample > 0 else 0.0)
                print(f"\n  [2-sample method]  cpu_delta={delta_2sample}  sys_delta={sys_delta_2sample}  → {pct_2sample:.1f}%")

            if isinstance(cpu2, int) and isinstance(pre2, int):
                delta_builtin = cpu2 - pre2
                sys_delta_builtin = (s2.get("cpu_stats",{}).get("system_cpu_usage",0)
                                   - s2.get("precpu_stats",{}).get("system_cpu_usage",0))
                ncpus = cpus2 or 1
                pct_builtin = (delta_builtin / sys_delta_builtin * ncpus * 100.0
                               if sys_delta_builtin > 0 else 0.0)
                print(f"  [precpu method]    cpu_delta={delta_builtin}  sys_delta={sys_delta_builtin}  → {pct_builtin:.1f}%")

            cli.close()

        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()

    # Also check via SSH for comparison
    print("\n[4] Comparison: docker stats --no-stream via SSH:")
    for i, w in enumerate(workers):
        vm_ip = db_manager.get_vm_ip_by_id(w.vm_id)
        try:
            out = run_ssh_command(vm_ip,
                f"docker stats --no-stream --format '{{{{.Name}}}}: {{{{.CPUPerc}}}}'",
                timeout=15).strip()
            print(f"  Worker {i}: {out}")
        except Exception as e:
            print(f"  Worker {i}: SSH error: {e}")

    flood_done.wait(timeout=FLOOD_SECS + 5)
    print("\n[CLEANUP]")
    scale(0)
    print("Done.")

if __name__ == "__main__":
    main()
