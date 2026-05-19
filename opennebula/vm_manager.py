"""
Low-level OpenNebula VM operations via pyone.
All other modules import from here instead of calling pyone directly.
"""

from opennebula.connection import get_client

# Template ID → name mapping (from OpenNebula)
TEMPLATES = {
    0: "Alpine Linux 3.20",
}
DEFAULT_TEMPLATE_ID = 0

VM_STATES = {
    0: "INIT",
    1: "PENDING",
    2: "HOLD",
    3: "ACTIVE",
    4: "STOPPED",
    5: "SUSPENDED",
    6: "DONE",
    7: "FAILED",
    8: "POWEROFF",
}

def create_vm(
    name: str,
    template_id: int = DEFAULT_TEMPLATE_ID,
    one_user_id: int = None,
    cpu: float = None,
    memory_mb: int = None,
    user_data: str = None,
) -> int:
    """
    Instantiate a VM from a template with optional hardware overrides and context.
    Returns the OpenNebula VM ID.
    """
    client = get_client()

    # Build extra configuration (template overrides)
    overrides = []
    if cpu:
        overrides.append(f'CPU="{cpu}"')
    if memory_mb:
        overrides.append(f'MEMORY="{memory_mb}"')

    context = [
        'NETWORK = "YES"',
        'TOKEN = "YES"'
    ]

    # If we have a user ID, try to fetch their public key from their OpenNebula profile
    if one_user_id is not None:
        try:
            user_info = client.user.info(one_user_id)
            # SSH_PUBLIC_KEY is in the user's TEMPLATE (dict-like object in pyone)
            template = getattr(user_info, 'TEMPLATE', {})
            public_key = None
            if isinstance(template, dict):
                public_key = template.get('SSH_PUBLIC_KEY')
            
            if public_key:
                context.append(f'SSH_PUBLIC_KEY = "{public_key}"')
            else:
                # Fallback to the template variable
                context.append('SSH_PUBLIC_KEY = "$USER[SSH_PUBLIC_KEY]"')
        except Exception as e:
            print(f"DEBUG: Could not fetch user {one_user_id} info: {e}")
            context.append('SSH_PUBLIC_KEY = "$USER[SSH_PUBLIC_KEY]"')
    else:
        context.append('SSH_PUBLIC_KEY = "$USER[SSH_PUBLIC_KEY]"')

    if user_data:
        # Escape double quotes for OpenNebula template syntax
        safe_data = user_data.strip().replace('\\', '\\\\').replace('"', '\\"')
        context.append(f'STARTUP_SCRIPT = "{safe_data}"')

    if context:
        overrides.append("CONTEXT = [ " + " , ".join(context) + " ]")

    extra_config = "\n".join(overrides)

    
    # Debug: you can check the generated config in the API logs
    print(f"DEBUG: Generating VM with config:\n{extra_config}")

    one_vm_id = client.template.instantiate(template_id, name, False, extra_config, False)
    if one_user_id is not None:
        # Transfer VM ownership from oneadmin to the actual user
        client.vm.chown(one_vm_id, one_user_id, -1)
    return one_vm_id


def destroy_vm(one_vm_id: int) -> None:
    """Terminate and delete a VM."""
    client = get_client()
    client.vm.action("terminate-hard", one_vm_id)


def get_vm(one_vm_id: int) -> dict:
    """Return a dict with the VM's current info and monitoring data."""
    client = get_client()
    vm = client.vm.info(one_vm_id)
    return _vm_to_dict(vm)


def list_all_vms() -> list[dict]:
    """Return all VMs across all users."""
    client = get_client()
    pool = client.vmpool.info(-2, -1, -1, -1)
    vms = pool.VM if hasattr(pool, "VM") else []
    return [_vm_to_dict(vm) for vm in vms]


def list_vms_by_one_user(one_user_id: int) -> list[dict]:
    """Return VMs owned by a specific OpenNebula user."""
    return [vm for vm in list_all_vms() if vm["one_owner_id"] == one_user_id]


def _vm_to_dict(vm) -> dict:
    monitoring = vm.MONITORING if hasattr(vm, "MONITORING") else None
    cpu_usage = float(getattr(monitoring, "CPU", 0) or 0) if monitoring else 0.0
    memory_kb = int(getattr(monitoring, "MEMORY", 0) or 0) if monitoring else 0

    # Extract IP address from NICs
    ip_address = "—"
    try:
        # vm.TEMPLATE is usually a dictionary in pyone for certain configurations
        template = getattr(vm, "TEMPLATE", {})
        if isinstance(template, dict):
            nics = template.get("NIC")
            if nics:
                if isinstance(nics, list) and len(nics) > 0:
                    ip_address = nics[0].get("IP", "—")
                elif isinstance(nics, dict):
                    ip_address = nics.get("IP", "—")
        
        # Fallback to CONTEXT if NIC doesn't have it
        if ip_address == "—" and isinstance(template, dict):
            context = template.get("CONTEXT", {})
            if isinstance(context, dict):
                ip_address = context.get("ETH0_IP", "—")
    except:
        pass

    return {
        "one_vm_id": vm.ID,
        "name": vm.NAME,
        "state": VM_STATES.get(vm.STATE, "UNKNOWN"),
        "state_code": vm.STATE,
        "lcm_state": vm.LCM_STATE,   # 3 = RUNNING (fully booted)
        "one_owner_id": vm.UID,
        "ip_address": ip_address,
        "cpu_usage_pct": round(cpu_usage * 100, 1),
        "memory_mb": round(memory_kb / 1024, 1),
    }
