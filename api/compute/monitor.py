"""
Cluster monitoring — collects CPU and memory metrics from all active VMs.
"""

from opennebula.vm_manager import list_all_vms


def get_cluster_metrics() -> dict:
    """
    Return aggregate metrics for all VMs currently in ACTIVE state.
    Used by the autoscaler and the /compute/status endpoint.
    """
    all_vms = list_all_vms()
    active_vms = [vm for vm in all_vms if vm["state"] == "ACTIVE" and vm.get("lcm_state") == 3]

    if not active_vms:
        return {
            "total_vms": len(all_vms),
            "active_vms": 0,
            "avg_cpu_pct": 0.0,
            "avg_memory_mb": 0.0,
            "vms": all_vms,
        }

    avg_cpu = sum(vm["cpu_usage_pct"] for vm in active_vms) / len(active_vms)
    avg_mem = sum(vm["memory_mb"] for vm in active_vms) / len(active_vms)

    return {
        "total_vms": len(all_vms),
        "active_vms": len(active_vms),
        "avg_cpu_pct": round(avg_cpu, 1),
        "avg_memory_mb": round(avg_mem, 1),
        "vms": all_vms,
    }
