"""
LB CPU Stress Test
==================
Proves the LB distributes CPU load across workers by:
  1. Deploying 2 nginx workers with gzip level 9 + a large compressible file
  2. Running many CONCURRENT HTTP requests through the LB (not sequential)
  3. Measuring CPU on BOTH workers while the flood is active
  4. Confirming request distribution via docker logs after the flood

CPU spikes through the LB because nginx must compress the large file per request.
20 parallel curl loops ensure enough concurrent work to register on both workers.
"""

import sys
import os
import time
import threading

os.environ.pop("SSH_AUTH_SOCK", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.loadbalancer.container_lb import scale_container_group
from api.loadbalancer.schemas import ContainerScaleRequest
from api.loadbalancer.ssh_utils import run_ssh_command, write_ssh_file
from api.database_service import db_manager

# ─── Config ──────────────────────────────────────────────────────────────────
USERNAME    = "angie"
GROUP_NAME  = "test-web-lb"
IMAGE       = "nginx:alpine"
PORT        = "80/tcp"
FLOOD_SECS  = 20          # How long to hammer the LB
PARALLEL    = 20          # Concurrent curl loops on the LB VM

# nginx config: gzip level 9 (CPU-heavy) + access log to stdout
NGINX_GZIP_CONF = """server {
    listen 80;
    server_name localhost;
    access_log /var/log/nginx/access.log;

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

def wait_running(vm_ip, cid, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = run_ssh_command(vm_ip,
                f"docker inspect --format '{{{{.State.Status}}}}' {cid}", timeout=8).strip()
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

def get_cpu_ssh(vm_ip, cid):
    """CPU% via docker stats --no-stream (single real-time snapshot from the VM)."""
    try:
        out = run_ssh_command(
            vm_ip,
            f"docker stats --no-stream --format '{{{{.CPUPerc}}}}' {cid}",
            timeout=12
        ).strip()
        return float(out.replace("%", "")) if out else 0.0
    except Exception:
        return 0.0

def count_requests(vm_ip, cname):
    """Count lines in docker logs (nginx:alpine writes access log to stdout)."""
    try:
        out = run_ssh_command(
            vm_ip, f"docker logs {cname} 2>/dev/null | wc -l", timeout=10
        ).strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0

def configure_worker(vm_ip, cname, idx):
    """Deploy gzip config + generate 4 MB compressible file in the worker."""
    tmp = f"/tmp/nginx_gzip_{idx}.conf"
    write_ssh_file(vm_ip, tmp, NGINX_GZIP_CONF)
    run_ssh_command(vm_ip, f"docker cp {tmp} {cname}:/etc/nginx/conf.d/default.conf")
    run_ssh_command(vm_ip, f"rm -f {tmp}")
    run_ssh_command(vm_ip, f"docker exec {cname} nginx -s reload")
    # Generate a 4 MB file of repeated text — highly compressible, forces real gzip work
    run_ssh_command(vm_ip,
        f"docker exec {cname} sh -c "
        f"\"yes 'CloudInfrastructure load-balancer CPU stress test data ABCDEFGHIJKLMNOP' "
        f"| head -c 4000000 > /usr/share/nginx/html/large.txt\""
    )

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65, flush=True)
    print("  LB CPU Stress Test — concurrent requests through LB", flush=True)
    print("=" * 65, flush=True)

    # ── Cleanup ──────────────────────────────────────────────────────────────
    print("\n[PRE-TEST] Cleanup (scale to 0)...", flush=True)
    try:
        scale(0)
        print("  ✓ Cleaned up.", flush=True)
    except Exception as e:
        print(f"  (cleanup skipped): {e}", flush=True)

    # ── Provision ────────────────────────────────────────────────────────────
    print("\n[STEP 1] Provisioning 2 workers + LB (no_autoscale=True)...", flush=True)
    t0 = time.time()
    data = scale(2, no_autoscale=True)
    elapsed = time.time() - t0
    print(f"  ✓ Done in {elapsed:.1f}s  —  LB: {data.load_balancer_address}", flush=True)

    workers = data.workers
    lb      = data.load_balancer
    if len(workers) < 2:
        print(f"  ✗ Only {len(workers)} worker(s). Aborting.")
        scale(0)
        return

    wm = []
    for i, w in enumerate(workers):
        ip = db_manager.get_vm_ip_by_id(w.vm_id)
        wm.append({"idx": i, "cid": w.container_id, "vm_ip": ip})
        print(f"  Worker {i}: {w.container_id[:12]} on VM {ip}", flush=True)

    lb_vm_ip     = db_manager.get_vm_ip_by_id(lb.vm_id)
    lb_host_port = lb.ports[PORT][0]["HostPort"]
    lb_url       = f"http://127.0.0.1:{lb_host_port}/large.txt"
    print(f"  LB URL (from VM {lb_vm_ip}): {lb_url}", flush=True)

    # ── Wait for containers ───────────────────────────────────────────────────
    print("\n[STEP 2] Waiting for containers to be running...", flush=True)
    for w in wm:
        ok = wait_running(w["vm_ip"], w["cid"])
        if not ok:
            print(f"  ✗ Worker {w['idx']} didn't start. Aborting.")
            scale(0)
            return
        w["cname"] = get_cname(w["vm_ip"], w["cid"])
        print(f"  ✓ Worker {w['idx']}: '{w['cname']}' running.", flush=True)

    # ── Configure workers ─────────────────────────────────────────────────────
    print("\n[STEP 3] Deploying gzip config + 4 MB test file on each worker...", flush=True)
    for w in wm:
        configure_worker(w["vm_ip"], w["cname"], w["idx"])
        print(f"  ✓ Worker {w['idx']} configured.", flush=True)

    # ── Connectivity check ────────────────────────────────────────────────────
    print(f"\n[STEP 4] Connectivity check...", flush=True)
    try:
        code = run_ssh_command(
            lb_vm_ip,
            f"curl -s -o /dev/null -w '%{{http_code}}' -H 'Accept-Encoding: gzip' {lb_url}",
            timeout=10
        ).strip()
        print(f"  ✓ LB → workers responded HTTP {code}", flush=True)
        if code not in ("200", "304"):
            print("  ✗ Unexpected status. Aborting.")
            scale(0)
            return
    except Exception as e:
        print(f"  ✗ Curl failed: {e}")
        scale(0)
        return

    # ── Baseline CPU ─────────────────────────────────────────────────────────
    print("\n[STEP 5] Baseline CPU (before flood)...", flush=True)
    baseline = []
    for w in wm:
        cpu = get_cpu_ssh(w["vm_ip"], w["cid"])
        baseline.append(cpu)
        print(f"  Worker {w['idx']} ({w['vm_ip']}): {cpu:.1f}%", flush=True)

    # ── Concurrent flood ─────────────────────────────────────────────────────
    # Launch PARALLEL concurrent curl loops on the LB VM for FLOOD_SECS seconds.
    # Uses 'date +%s' for timing — POSIX-compatible on Alpine/ash.
    # NOTE: $SECONDS is bash-only and DOES NOT work in subshells on Alpine.
    PARALLEL = 30
    flood_cmd = (
        f"end=$(( $(date +%s) + {FLOOD_SECS} )); "
        f"for i in $(seq 1 {PARALLEL}); do "
        f"  ( while [ $(date +%s) -lt $end ]; do "
        f"      curl -s -H 'Accept-Encoding: gzip' -o /dev/null {lb_url}; "
        f"    done ) & "
        f"done; "
        f"wait"
    )

    print(f"\n[STEP 6] Flooding LB with {PARALLEL} concurrent curl loops for {FLOOD_SECS}s...", flush=True)

    flood_done = threading.Event()

    def run_flood():
        try:
            run_ssh_command(lb_vm_ip, flood_cmd, timeout=FLOOD_SECS + 15)
        except Exception as e:
            print(f"  (flood error): {e}", flush=True)
        finally:
            flood_done.set()

    flood_thread = threading.Thread(target=run_flood, daemon=True)
    flood_thread.start()

    # Sample CPU at two points during the flood
    samples = {w["idx"]: [] for w in wm}

    for sample_num in range(3):
        wait_secs = 5 if sample_num == 0 else 5
        print(f"  * Waiting {wait_secs}s before CPU sample {sample_num + 1}/3...", flush=True)
        time.sleep(wait_secs)
        if flood_done.is_set():
            print("  (flood ended early)", flush=True)
            break
        for w in wm:
            cpu = get_cpu_ssh(w["vm_ip"], w["cid"])
            samples[w["idx"]].append(cpu)
            print(f"    Worker {w['idx']} ({w['vm_ip']}): {cpu:.1f}% CPU", flush=True)

    print("  * Waiting for flood to complete...", flush=True)
    flood_thread.join(timeout=FLOOD_SECS + 20)

    # ── Post-flood CPU ────────────────────────────────────────────────────────
    print("\n[STEP 7] Post-flood CPU (should drop back to ~0%)...", flush=True)
    post = []
    for w in wm:
        cpu = get_cpu_ssh(w["vm_ip"], w["cid"])
        post.append(cpu)
        print(f"  Worker {w['idx']}: {cpu:.1f}%", flush=True)

    # ── Count request distribution ────────────────────────────────────────────
    print("\n[STEP 8] Request distribution (nginx docker logs)...", flush=True)
    counts = []
    for w in wm:
        c = count_requests(w["vm_ip"], w["cname"])
        counts.append(c)
        print(f"  Worker {w['idx']} ({w['vm_ip']}): {c} requests", flush=True)
    total = sum(counts)

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  RESULTS SUMMARY")
    print("=" * 65)

    print(f"\n📊 Request Distribution (LB round-robin):")
    print(f"  {'Worker':<10} {'Requests':>10}  {'Share':>8}")
    print("  " + "-" * 32)
    dist_ok = all(c > 0 for c in counts)
    for i, w in enumerate(wm):
        share = counts[i] / total * 100 if total else 0
        flag  = "✅" if counts[i] > 0 else "❌"
        print(f"  Worker {i:<3}   {counts[i]:>8}   {share:>7.1f}%  {flag}")
    print(f"  Total: {total} requests handled")
    print(f"\n  {'✅ LB distributed traffic to ALL workers.' if dist_ok else '⚠️  Some workers got 0 requests.'}")

    print(f"\n🔥 CPU via LB flood (peak of {len(next(iter(samples.values())))} samples):")
    print(f"  {'Worker':<10} {'Baseline':>10}  {'Peak CPU':>10}  {'Delta':>8}  {'Stressed?':>10}")
    print("  " + "-" * 55)
    cpu_ok = True
    for i, w in enumerate(wm):
        s = samples[w["idx"]]
        peak = max(s) if s else 0.0
        delta = peak - baseline[i]
        stressed = peak > baseline[i] + 5.0
        flag = "✅" if stressed else "❌"
        if not stressed:
            cpu_ok = False
        print(f"  Worker {i:<3}   {baseline[i]:>8.1f}%  {peak:>8.1f}%  {delta:>+6.1f}%  {flag}")
    print(f"\n  {'✅ PASS — CPU spiked on ALL workers via LB requests.' if cpu_ok else '⚠️  CPU did not spike via LB (nginx may be too fast for this load).'}")

    # ── Cleanup ──────────────────────────────────────────────────────────────
    print("\n[CLEANUP] Scaling to 0...", flush=True)
    scale(0)
    print("[OK] Done.\n" + "=" * 65)

if __name__ == "__main__":
    main()
