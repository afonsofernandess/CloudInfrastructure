"""
Autoscaler End-to-End Verification Test
========================================
Key design: the flood starts IMMEDIATELY after provisioning so the
autoscaler's very first CPU check (at 10s) already sees high load.
Workers are configured in parallel with the flood.

  PHASE 1 — Scale-UP:
    - Provision 2 workers (no no_autoscale)
    - Start flood thread IMMEDIATELY (before config)
    - Configure gzip + test file in parallel
    - Poll for 2→3 replicas

  PHASE 2 — Scale-DOWN:
    - Flood stops → CPU drops
    - Watch for scale-down back to 1

Requires API server RESTARTED with the fixed 2-sample CPU code.
"""

import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

os.environ.pop("SSH_AUTH_SOCK", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.loadbalancer.container_lb import scale_container_group, get_container_group_details
from api.loadbalancer.schemas import ContainerScaleRequest
from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file
from api.database_service import db_manager

USERNAME   = "angie"
GROUP_NAME = "autoscale-test"
IMAGE      = "nginx:alpine"
PORT       = "80/tcp"
FLOOD_SECS = 90    # Long flood — gives autoscaler plenty of check windows
PARALLEL   = 25    # 25 loops → enough to push avg CPU above 20% with gzip on 5MB

NGINX_GZIP_CONF = """server {
    listen 80;
    server_name localhost;
    gzip on;
    gzip_comp_level 9;
    gzip_min_length 1;
    gzip_types text/plain application/octet-stream;
    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
    }
}
"""

# ─── Helpers ─────────────────────────────────────────────────────────────────

def scale(replicas, no_autoscale=False):
    req = ContainerScaleRequest(
        name=GROUP_NAME, image=IMAGE,
        replicas=replicas, container_port=PORT,
        no_autoscale=no_autoscale
    )
    return scale_container_group(USERNAME, req)

def get_replicas():
    try:
        data = get_container_group_details(USERNAME, GROUP_NAME)
        return data.replicas_count, data.workers
    except Exception as e:
        print(f"  (get_replicas error: {e})", flush=True)
        return None, []

def wait_running(vm_ip, cid, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = run_ssh_command(
                vm_ip, f"docker inspect --format '{{{{.State.Status}}}}' {cid}", timeout=8
            ).strip()
            if s == "running":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False

def get_cname(vm_ip, cid):
    return run_ssh_command(
        vm_ip, f"docker inspect --format '{{{{.Name}}}}' {cid}", timeout=8
    ).strip().lstrip("/")

def configure_worker(vm_ip, cname, idx):
    """
    Configure gzip + create a 5MB compressible test file.
    Uses 'seq' on the host for fast file generation, then docker cp.
    """
    # Write gzip config
    tmp_conf = f"/tmp/nginx_as_{idx}.conf"
    write_ssh_file(vm_ip, tmp_conf, NGINX_GZIP_CONF)
    run_ssh_command(vm_ip, f"docker cp {tmp_conf} {cname}:/etc/nginx/conf.d/default.conf")
    run_ssh_command(vm_ip, f"rm -f {tmp_conf}")
    run_ssh_command(vm_ip, f"docker exec {cname} nginx -s reload")

    # Generate 5MB compressible file on the HOST VM, then copy into container.
    # seq 1 1000000 ≈ 5MB of highly compressible text — gzip level 9 on this uses real CPU.
    tmp_file = f"/tmp/large_as_{idx}.txt"
    run_ssh_command(vm_ip, f"seq 1 1000000 > {tmp_file}")
    run_ssh_command(vm_ip, f"docker cp {tmp_file} {cname}:/usr/share/nginx/html/large.txt")
    run_ssh_command(vm_ip, f"rm -f {tmp_file}")

def start_flood(lb_vm_ip, lb_url, flood_done_event):
    """Run PARALLEL concurrent curl loops for FLOOD_SECS on the LB VM."""
    flood_cmd = (
        f"end=$(( $(date +%s) + {FLOOD_SECS} )); "
        f"for i in $(seq 1 {PARALLEL}); do "
        f"  ( while [ $(date +%s) -lt $end ]; do "
        f"      curl -s -H 'Accept-Encoding: gzip' -o /dev/null {lb_url}; "
        f"    done ) & "
        f"done; "
        f"wait"
    )
    try:
        run_ssh_command(lb_vm_ip, flood_cmd, timeout=FLOOD_SECS + 30)
    except Exception as e:
        print(f"  (flood error): {e}", flush=True)
    finally:
        flood_done_event.set()

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65, flush=True)
    print("  Autoscaler End-to-End Verification Test", flush=True)
    print(f"  Scale-UP  : avg CPU > 20%  (check every 10s, cooldown 30s)", flush=True)
    print(f"  Scale-DOWN: avg CPU < 5%", flush=True)
    print("  Strategy  : flood starts BEFORE config — autoscaler sees load", flush=True)
    print("=" * 65, flush=True)

    # ── Cleanup ──────────────────────────────────────────────────────────────
    print("\n[PRE-TEST] Cleanup...", flush=True)
    try:
        scale(0)
        print("  ✓ Cleaned up.", flush=True)
    except Exception as e:
        print(f"  (skipped): {e}", flush=True)

    # ── Provision ────────────────────────────────────────────────────────────
    print("\n[STEP 1] Provisioning 2 workers (no_autoscale=False)...", flush=True)
    t0 = time.time()
    data = scale(2, no_autoscale=False)
    print(f"  ✓ Done in {time.time()-t0:.1f}s  —  LB: {data.load_balancer_address}", flush=True)

    workers = data.workers
    lb      = data.load_balancer
    if len(workers) < 2:
        print(f"  ✗ Only {len(workers)} worker(s). Aborting.")
        scale(0)
        return

    lb_vm_ip     = db_manager.get_vm_ip_by_id(lb.vm_id)
    lb_host_port = lb.ports[PORT][0]["HostPort"]
    lb_url_default = f"http://127.0.0.1:{lb_host_port}/"
    lb_url_large   = f"http://127.0.0.1:{lb_host_port}/large.txt"

    for i, w in enumerate(workers):
        ip = db_manager.get_vm_ip_by_id(w.vm_id)
        print(f"  Worker {i}: {w.container_id[:12]} on VM {ip}", flush=True)
    print(f"  LB on VM {lb_vm_ip}, port {lb_host_port}", flush=True)

    # ── Wait for containers ───────────────────────────────────────────────────
    print("\n[STEP 2] Waiting for containers to be running...", flush=True)
    for i, w in enumerate(workers):
        vm_ip = db_manager.get_vm_ip_by_id(w.vm_id)
        wait_running(vm_ip, w.container_id)
        print(f"  ✓ Worker {i} running.", flush=True)

    # ── Configure workers in PARALLEL before flood ───────────────────────────
    # Both workers configured simultaneously using threads — completes in ~5-8s
    # total, minimising the window before the flood starts.
    print("\n[STEP 3] Configuring workers in parallel (gzip + 2MB test file)...", flush=True)
    config_errors = []

    def configure_one(w):
        vm_ip = db_manager.get_vm_ip_by_id(w.vm_id)
        cname = get_cname(vm_ip, w.container_id)
        configure_worker(vm_ip, cname, workers.index(w))
        return cname

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(configure_one, w): i for i, w in enumerate(workers)}
        for fut, idx in futures.items():
            try:
                cname = fut.result(timeout=60)
                print(f"  ✓ Worker {idx} ({cname}) configured.", flush=True)
            except Exception as e:
                print(f"  ✗ Worker {idx} config failed: {e}", flush=True)
                config_errors.append(idx)

    if config_errors:
        print("  ✗ Configuration failed. Aborting.")
        scale(0)
        return

    # ── NOW start the flood (workers are fully configured) ────────────────────
    print(f"\n[STEP 4] Starting flood ({PARALLEL} concurrent loops for {FLOOD_SECS}s on /large.txt)...", flush=True)
    flood_done = threading.Event()
    flood_thread = threading.Thread(
        target=start_flood, args=(lb_vm_ip, lb_url_large, flood_done), daemon=True
    )
    flood_thread.start()
    print(f"  ✓ Flood running.", flush=True)

    # ── PHASE 1: Poll for scale-UP ────────────────────────────────────────────
    print(f"\n{'='*65}", flush=True)
    print(f"  PHASE 1: Watching for autoscaler to add a 3rd replica...", flush=True)
    print(f"  (autoscaler checks every 10s, needs avg CPU > 50%)", flush=True)
    print(f"{'='*65}", flush=True)

    scale_up_detected = False
    peak_replicas = 2
    poll_start = time.time()

    while not flood_done.is_set():
        time.sleep(10)
        count, ws = get_replicas()
        elapsed = time.time() - poll_start
        if count is not None:
            ids = [w.container_id[:8] for w in ws]
            arrow = "🚀" if count > peak_replicas else "  "
            print(f"  {arrow} [{elapsed:5.0f}s] {count} replicas  {ids}", flush=True)
            if count > peak_replicas:
                peak_replicas = count
                scale_up_detected = True
                print(f"       ↑ AUTOSCALER SCALED UP to {count} replicas!", flush=True)
        else:
            print(f"     [{elapsed:5.0f}s] (scan returned no data — may be mid-rescale)", flush=True)

    # one final check after flood ends
    time.sleep(5)
    count, ws = get_replicas()
    if count and count > peak_replicas:
        peak_replicas = count
        scale_up_detected = True
        print(f"  🚀 Final check: {count} replicas (scale-up detected late)", flush=True)

    print(f"\n  Flood complete. Peak replicas: {peak_replicas}", flush=True)

    # ── PHASE 2: Watch for scale-DOWN ─────────────────────────────────────────
    print(f"\n{'='*65}", flush=True)
    print(f"  PHASE 2: Load stopped — watching for scale-DOWN (up to 90s)...", flush=True)
    print(f"{'='*65}", flush=True)

    scale_down_detected = False
    wait_start = time.time()

    while time.time() - wait_start < 90:
        time.sleep(10)
        count, _ = get_replicas()
        elapsed = time.time() - wait_start
        if count is not None:
            arrow = "📉" if count < peak_replicas else "  "
            print(f"  {arrow} [{elapsed:5.0f}s] {count} replicas", flush=True)
            if count < peak_replicas:
                print(f"       ↓ AUTOSCALER SCALED DOWN to {count} replicas!", flush=True)
                scale_down_detected = True
                break
        else:
            print(f"     [{elapsed:5.0f}s] (scan returned no data)", flush=True)

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  AUTOSCALER TEST RESULTS")
    print("=" * 65)
    print(f"  Scale-UP   (avg CPU >20% → new replica): {'✅ PASS' if scale_up_detected   else '❌ FAIL'}")
    print(f"  Scale-DOWN (avg CPU <5%  → drop replica): {'✅ PASS' if scale_down_detected else '❌ FAIL'}")
    print(f"  Peak replicas seen: {peak_replicas}")

    if not scale_up_detected:
        print("\n  ⚠️  Scale-up did not trigger. Check server logs for:")
        print("     'ContainerAutoscale monitor for autoscale-test'")
        print("     If CPU shows 0.0% → API server was NOT restarted.")
        print("     Restart uvicorn and re-run this test.")

    # ── Cleanup ──────────────────────────────────────────────────────────────
    print("\n[CLEANUP] Scaling to 0...", flush=True)
    scale(0)
    print("[OK] Done.\n" + "=" * 65)

if __name__ == "__main__":
    main()
