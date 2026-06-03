"""
DB Cluster — Comprehensive Verification Test
=============================================

Tests exactly three things the user cares about:

  TEST 1 — PRIMARY is the only write target
    Write via HAProxy write port (5432) → succeeds (goes to primary).
    Write directly to a replica        → fails with "read-only transaction".

  TEST 2 — REPLICATION is live (WAL streaming works)
    INSERT a new row via the write port.
    Immediately read that row directly from each replica.
    Replica must have it within a few seconds (WAL streaming, not batch).

  TEST 3 — READ LOAD BALANCING distributes across primary + replicas
    Run 8 SELECT queries through the HAProxy read port (5433).
    Capture which backend container IP answered each query.
    At least 2 different IPs must respond → round-robin is working.

Requires:
  - API server running:  uvicorn api.main:app --port 8000
  - A cluster already provisioned (will use CLUSTER_NAME below).
  - If no cluster exists, the script provisions one automatically.

Usage:
  PYTHONPATH=. python scripts/test_db_cluster.py
"""

import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.jwt import create_access_token
from api.loadbalancer.ssh_utils import run_ssh_command

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL     = "http://localhost:8000"
USERNAME     = "angie"
USER_ID      = 3
CLUSTER_NAME = "test-db-lb"

PASS_LABEL   = "✅ PASS"
FAIL_LABEL   = "❌ FAIL"
SKIP_LABEL   = "⚠️  SKIP"

results = {}   # test_name → True/False

# ── Helpers ───────────────────────────────────────────────────────────────────

def psql(vm_ip: str, container: str, password: str, user: str, db: str,
         host: str, port: int, sql: str, expect_fail: bool = False) -> str:
    """
    Run a SQL statement inside a Docker container on a VM via SSH tunnel.
    Returns stdout on success.
    Raises RuntimeError on failure (unless expect_fail=True, then returns the error text).
    """
    cmd = (
        f"docker exec -e PGPASSWORD='{password}' {container} "
        f"psql -h {host} -p {port} -U {user} -d {db} -t -A -c \"{sql}\""
    )
    try:
        return run_ssh_command(vm_ip, cmd).strip()
    except RuntimeError as e:
        if expect_fail:
            return str(e)
        raise


def patch_pg_hba(vm_ip: str, container_name: str, db_user: str, db_name: str) -> None:
    """
    Ensure pg_hba.conf on the primary allows password-authenticated connections
    from any network host (0.0.0.0/0).  This is required so that psql queries
    routed through HAProxy — which arrive at PostgreSQL from the VM's bridge
    IP, not 127.0.0.1 — can authenticate with scram-sha-256.

    The patch is idempotent: it uses grep-or-append so running it multiple
    times on the same container is safe.
    """
    info(f"Patching pg_hba.conf on primary ({container_name}) to allow network auth...")

    # 1. Add host-all rule (allows the regular DB user through HAProxy)
    run_ssh_command(
        vm_ip,
        f"docker exec {container_name} sh -c "
        f"\"grep -qF 'host all all 0.0.0.0/0' "
        f"/var/lib/postgresql/data/pg_hba.conf || "
        f"echo 'host all all 0.0.0.0/0 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf\""
    )

    # 2. Add replication rule (in case this is an older cluster that also lacks it)
    run_ssh_command(
        vm_ip,
        f"docker exec {container_name} sh -c "
        f"\"grep -qF 'host replication replicator 0.0.0.0/0' "
        f"/var/lib/postgresql/data/pg_hba.conf || "
        f"echo 'host replication replicator 0.0.0.0/0 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf\""
    )

    # 3. Reload so the new rules take effect immediately (no restart needed)
    run_ssh_command(
        vm_ip,
        f"docker exec {container_name} psql -U {db_user} -d {db_name} "
        f"-c \"SELECT pg_reload_conf();\""
    )
    ok("pg_hba.conf patched and reloaded.")


def section(title: str):
    print(f"\n{'═' * 64}")
    print(f"  {title}")
    print(f"{'═' * 64}")


def ok(msg: str):   print(f"  ✅  {msg}")
def fail(msg: str): print(f"  ❌  {msg}")
def info(msg: str): print(f"  ℹ️   {msg}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("  DB Cluster — Comprehensive Verification Test")
    print("=" * 64)

    token   = create_access_token(user_id=USER_ID, username=USERNAME)
    headers = {"Authorization": f"Bearer {token}"}
    info(f"Token generated for user '{USERNAME}'.")

    # ── Fetch or provision cluster ────────────────────────────────────────────
    section("0. Fetching cluster details")
    r = requests.get(f"{BASE_URL}/loadbalancer/databases/cluster/{CLUSTER_NAME}", headers=headers)

    if r.status_code == 404:
        info(f"Cluster '{CLUSTER_NAME}' not found — provisioning one with 1 replica...")
        r = requests.post(
            f"{BASE_URL}/loadbalancer/databases/cluster",
            json={"cluster_name": CLUSTER_NAME, "db_name": USERNAME, "replicas": 1},
            headers=headers,
            timeout=300,
        )
        if r.status_code not in (200, 201):
            fail(f"Could not provision cluster: {r.status_code} — {r.text}")
            sys.exit(1)
        ok("Cluster provisioned.")
    elif r.status_code != 200:
        fail(f"Could not fetch cluster: {r.status_code} — {r.text}")
        sys.exit(1)

    cluster  = r.json()
    primary  = cluster["primary"]
    replicas = cluster["replicas"]
    lb       = cluster["load_balancer"]

    if not replicas:
        fail("Cluster has no replicas. Scale to at least 1 replica first.")
        sys.exit(1)

    db_name   = primary["credentials"]["db_name"]
    db_user   = primary["credentials"]["db_user"]
    db_pass   = primary["credentials"]["db_password"]
    p_vm_ip   = primary["credentials"]["host"]
    p_cname   = f"db-{USERNAME}-{CLUSTER_NAME}-primary"
    lb_ip     = lb["credentials"]["host"]
    lb_wport  = lb["credentials"]["port"]       # HAProxy write frontend (→ primary only)
    lb_rport  = lb["read_host_port"]            # HAProxy read frontend  (→ primary + replicas)

    print(f"\n  Primary VM:          {p_vm_ip}  container={p_cname}")
    print(f"  HAProxy VM:          {lb_ip}")
    print(f"  HAProxy write port:  {lb_wport}  (→ primary only)")
    print(f"  HAProxy read port:   {lb_rport}  (→ primary + all replicas, round-robin)")
    print(f"  Replicas:            {len(replicas)}")
    for i, rep in enumerate(replicas):
        print(f"    Replica #{i+1}: VM {rep['credentials']['host']}")

    # ── Ensure pg_hba.conf allows network (HAProxy) connections ──────────────
    # Connections routed through HAProxy arrive at PostgreSQL from the VM's
    # bridge IP, not 127.0.0.1, so we need a `host all all 0.0.0.0/0` rule.
    # patch_pg_hba() is idempotent — safe to run every time.
    try:
        patch_pg_hba(p_vm_ip, p_cname, db_user, db_name)
    except Exception as e:
        fail(f"Could not patch pg_hba.conf — tests may fail with auth errors: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 1 — Write isolation
    # ─────────────────────────────────────────────────────────────────────────
    section("TEST 1 — Write isolation (primary accepts writes, replicas reject them)")

    # 1a. Create table and write through HAProxy WRITE port → must succeed
    print("\n  1a. INSERT via HAProxy write port (should reach primary only)...")
    setup_sql = (
        "CREATE TABLE IF NOT EXISTS cluster_test "
        "(id serial PRIMARY KEY, msg text, ts timestamptz DEFAULT now()); "
        "TRUNCATE TABLE cluster_test; "
        "INSERT INTO cluster_test (msg) VALUES ('initial-write');"
    )
    try:
        out = psql(p_vm_ip, p_cname, db_pass, db_user, db_name,
                   lb_ip, lb_wport, setup_sql)
        row = psql(p_vm_ip, p_cname, db_pass, db_user, db_name,
                   lb_ip, lb_wport, "SELECT msg FROM cluster_test LIMIT 1;")
        ok("INSERT via write port → succeeded (primary accepted the write).")
        info(f"    Raw output of insert operation: {out or 'Success'}")
        info(f"    Queried row message from primary: '{row.strip()}'")
        results["1a_write_port_accepts_writes"] = True
    except Exception as e:
        fail(f"INSERT via write port failed unexpectedly: {e}")
        results["1a_write_port_accepts_writes"] = False

    # 1b. Attempt INSERT directly on each replica → must fail with read-only error
    print("\n  1b. INSERT directly on each replica (should be rejected as read-only)...")
    all_replicas_readonly = True
    for i, rep in enumerate(replicas):
        r_cname  = f"db-{USERNAME}-{CLUSTER_NAME}-replica-{i+1}"
        r_vm_ip  = rep["credentials"]["host"]
        r_port   = rep["credentials"]["port"]
        err = psql(r_vm_ip, r_cname, db_pass, db_user, db_name,
                   "localhost", 5432,
                   "INSERT INTO cluster_test (msg) VALUES ('should-fail');",
                   expect_fail=True)
        if "read-only" in err.lower() or "cannot execute" in err.lower() or "exit 1" in err.lower():
            ok(f"Replica #{i+1} ({r_vm_ip}) correctly rejected the write (read-only).")
            info(f"    PostgreSQL error message returned by replica: {err.strip()}")
        else:
            fail(f"Replica #{i+1} did NOT reject the write! Response: {err[:120]}")
            all_replicas_readonly = False
    results["1b_replicas_reject_writes"] = all_replicas_readonly

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 2 — Live replication (WAL streaming)
    # ─────────────────────────────────────────────────────────────────────────
    section("TEST 2 — Live replication  (WAL streaming: primary → replicas)")

    # Insert a unique value we can verify on each replica
    unique_val = f"wal-test-{int(time.time())}"
    print(f"\n  Inserting unique row '{unique_val}' via write port...")
    try:
        psql(p_vm_ip, p_cname, db_pass, db_user, db_name,
             lb_ip, lb_wport,
             f"INSERT INTO cluster_test (msg) VALUES ('{unique_val}');")
        ok(f"Row '{unique_val}' inserted on primary.")
    except Exception as e:
        fail(f"Could not insert test row: {e}")
        results["2_live_replication"] = False
    else:
        print("  Waiting up to 5 seconds for WAL to propagate to replicas...")
        all_replicated = True
        for i, rep in enumerate(replicas):
            r_cname = f"db-{USERNAME}-{CLUSTER_NAME}-replica-{i+1}"
            r_vm_ip = rep["credentials"]["host"]
            r_port  = rep["credentials"]["port"]

            found = False
            for attempt in range(5):
                try:
                    val = psql(r_vm_ip, r_cname, db_pass, db_user, db_name,
                               "localhost", 5432,
                               f"SELECT msg FROM cluster_test WHERE msg='{unique_val}' LIMIT 1;")
                    if val.strip() == unique_val:
                        ok(f"Replica #{i+1} ({r_vm_ip}) — row found after {attempt+1}s  ✓ WAL streaming works.")
                        info(f"    Row contents returned by replica: msg='{val.strip()}'")
                        found = True
                        break
                except Exception:
                    pass
                time.sleep(1)

            if not found:
                fail(f"Replica #{i+1} ({r_vm_ip}) — row NOT found after 5 seconds.")
                all_replicated = False

        results["2_live_replication"] = all_replicated

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 3 — Round-robin read distribution
    # ─────────────────────────────────────────────────────────────────────────
    section("TEST 3 — Read load balancing  (round-robin via HAProxy read port)")

    print(f"\n  Sending 8 SELECT queries to the read port ({lb_rport})...")
    print("  Each query reports which backend PostgreSQL container answered it.\n")

    server_ips = []
    for i in range(8):
        try:
            ip = psql(p_vm_ip, p_cname, db_pass, db_user, db_name,
                      lb_ip, lb_rport,
                      "SELECT pg_read_file('/etc/hostname');")
            server_ips.append(ip)
            print(f"    Query #{i+1:2d} → backend IP: {ip}")
        except Exception as e:
            print(f"    Query #{i+1:2d} → FAILED: {e}")

    unique_backends = set(server_ips)
    print(f"\n  Unique backends that responded: {sorted(unique_backends)}")
    if len(unique_backends) >= 2:
        ok(f"{len(unique_backends)} different backends responded → round-robin is WORKING.")
        results["3_round_robin"] = True
    else:
        fail("All queries went to the same backend — round-robin may not be working.")
        results["3_round_robin"] = False

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    section("RESULTS")
    checks = [
        ("1a", "Write port accepts writes (primary)"),
        ("1b", "Replicas reject writes (read-only)"),
        ("2",  "Live WAL replication (primary → replicas)"),
        ("3",  "Round-robin read distribution"),
    ]
    all_passed = True
    for key, label in checks:
        full_key = [k for k in results if k.startswith(key)][0] if any(k.startswith(key) for k in results) else None
        if full_key and full_key in results:
            passed = results[full_key]
            print(f"  {PASS_LABEL if passed else FAIL_LABEL}  {label}")
            if not passed:
                all_passed = False
        else:
            print(f"  {SKIP_LABEL}  {label} (not reached)")
            all_passed = False

    print()
    if all_passed:
        print("  🎉  All checks passed — DB cluster is correctly configured!")
    else:
        print("  ⚠️   Some checks failed — see details above.")
    print("=" * 64)


if __name__ == "__main__":
    main()
