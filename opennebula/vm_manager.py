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
    cpu: float = None,
    memory_mb: int = None,
    disk_gb: int = None,
    user_data: str = None,
    user_id: int = None,
    group_id: int = None,
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
    if user_id is not None:
        try:
            user_info = client.user.info(user_id)
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

    # Detect OS from template name to install Docker using the correct package manager
    is_ubuntu = False
    try:
        client = get_client()
        template_info = client.template.info(template_id)
        template_name = str(getattr(template_info, "NAME", "")).lower()
        if "ubuntu" in template_name:
            is_ubuntu = True
    except Exception as e:
        print(f"DEBUG: Could not check template OS, defaulting to Alpine: {e}")

    if is_ubuntu:
        docker_setup = (
            'rm -f /etc/resolv.conf\n'
            'echo "nameserver 8.8.8.8" > /etc/resolv.conf\n'
            'echo "nameserver 1.1.1.1" >> /etc/resolv.conf\n'
            '# Wait up to 30 seconds for internet connectivity\n'
            'i=0\n'
            'while [ $i -lt 30 ]; do\n'
            '  if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then\n'
            '    break\n'
            '  fi\n'
            '  sleep 1\n'
            '  i=$((i+1))\n'
            'done\n'
            '# Install docker on Ubuntu with retries\n'
            'for r in 1 2 3; do\n'
            '  apt-get update -y && apt-get install -y docker.io && break\n'
            '  sleep 5\n'
            'done\n'
            'systemctl enable docker\n'
            'systemctl start docker\n'
            'usermod -aG docker ubuntu || true\n'
        )
    else:
        docker_setup = (
            'rm -f /etc/resolv.conf\n'
            'echo "nameserver 8.8.8.8" > /etc/resolv.conf\n'
            'echo "nameserver 1.1.1.1" >> /etc/resolv.conf\n'
            '# Wait up to 30 seconds for internet connectivity\n'
            'i=0\n'
            'while [ $i -lt 30 ]; do\n'
            '  if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then\n'
            '    break\n'
            '  fi\n'
            '  sleep 1\n'
            '  i=$((i+1))\n'
            'done\n'
            '# Install docker on Alpine with retries\n'
            'for r in 1 2 3; do\n'
            '  apk update && apk add docker && break\n'
            '  sleep 5\n'
            'done\n'
            'rc-update add docker default\n'
            '(sleep 10 && service docker start) &\n'
        )
    if user_data:
        full_user_data = docker_setup + user_data
    else:
        full_user_data = "#!/bin/sh\n" + docker_setup

    import base64
    script_b64 = base64.b64encode(full_user_data.strip().encode()).decode()
    context.append(f'START_SCRIPT_BASE64 = "{script_b64}"')

    if context:
        overrides.append("CONTEXT = [ " + " , ".join(context) + " ]")

    # Override root disk size if custom disk_gb is requested
    if disk_gb:
        disk_size_mb = disk_gb * 1024
        overrides.append(f'DISK = [ SIZE = "{disk_size_mb}" ]')

    extra_config = "\n".join(overrides)

    
    # Debug: you can check the generated config in the API logs
    print(f"DEBUG: Generating VM with config:\n{extra_config}")

    one_vm_id = client.template.instantiate(template_id, name, False, extra_config, False)
    # CHOWN to the correct user so they can see it in their dashboard
    if user_id is not None:
        # gid -1 means keep current group
        client.vm.chown(one_vm_id, user_id, group_id if group_id is not None else -1)
    return one_vm_id


def destroy_vm(one_vm_id: int) -> None:
    """Terminate and delete a VM."""
    client = get_client()
    client.vm.action("terminate-hard", one_vm_id)


def suspend_vm(one_vm_id: int) -> None:
    """Suspend a VM to save resources."""
    client = get_client()
    client.vm.action("suspend", one_vm_id)


def resume_vm(one_vm_id: int) -> None:
    """Resume a suspended or powered-off VM."""
    client = get_client()
    client.vm.action("resume", one_vm_id)



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
    
    # We call client.vm.info(vm.ID) for each VM to get the most 
    # up-to-date MONITORING data, which can be stale in the pool list.
    return [_vm_to_dict(client.vm.info(vm.ID)) for vm in vms]


def list_vms_by_one_user(one_user_id: int) -> list[dict]:
    """Return VMs owned by a specific OpenNebula user."""
    return [vm for vm in list_all_vms() if vm["one_owner_id"] == one_user_id]


def _vm_to_dict(vm) -> dict:
    monitoring = getattr(vm, "MONITORING", {})
    
    # Try to get CPU and Memory from monitoring (handle both object and dict)
    cpu_usage = 0.0
    memory_kb = 0
    
    if isinstance(monitoring, dict):
        cpu_usage = float(monitoring.get("CPU", 0) or 0)
        memory_kb = int(monitoring.get("MEMORY", 0) or 0)
    else:
        cpu_usage = float(getattr(monitoring, "CPU", 0) or 0)
        memory_kb = int(getattr(monitoring, "MEMORY", 0) or 0)

    # Extract IP address and disk size from template
    ip_address = "—"
    disk_gb = 2.0
    try:
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

        # Extract disk size (SIZE in MB) and allocated memory (MEMORY in MB)
        memory_limit_mb = 2048.0
        if isinstance(template, dict):
            disks = template.get("DISK")
            if disks:
                if isinstance(disks, list) and len(disks) > 0:
                    size_mb = disks[0].get("SIZE")
                    if size_mb:
                        disk_gb = round(float(size_mb) / 1024, 1)
                elif isinstance(disks, dict):
                    size_mb = disks.get("SIZE")
                    if size_mb:
                        disk_gb = round(float(size_mb) / 1024, 1)

            mem = template.get("MEMORY")
            if mem:
                memory_limit_mb = float(mem)
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
        "cpu_usage_pct": round(cpu_usage, 1),
        "memory_mb": round(memory_kb / 1024, 1),
        "memory_limit_mb": memory_limit_mb,
        "disk_gb": disk_gb,
    }


def list_templates() -> list[dict]:
    """Return a list of all VM templates available in OpenNebula."""
    try:
        client = get_client()
        pool = client.templatepool.info(-2, -1, -1)
        templates = pool.VMTEMPLATE if hasattr(pool, "VMTEMPLATE") else []
        if not isinstance(templates, list):
            templates = [templates]
            
        result = []
        for t in templates:
            result.append({
                "id": int(t.ID),
                "name": str(t.NAME),
            })
        if result:
            return result
    except Exception as e:
        print(f"WARNING: failed to list templates from OpenNebula: {e}")
        
    # Fallback to local hardcoded mapping
    return [{"id": k, "name": v} for k, v in TEMPLATES.items()]


_TEMPLATE_USER_CACHE = {}

def get_ssh_user_by_template(template_id: int) -> str:
    """Return the default SSH user for a template ID (cached)."""
    if template_id == 0:
        return "root"
    if template_id in _TEMPLATE_USER_CACHE:
        return _TEMPLATE_USER_CACHE[template_id]
        
    user = "root"
    try:
        client = get_client()
        template_info = client.template.info(template_id)
        name = str(getattr(template_info, "NAME", "")).lower()
        if "ubuntu" in name:
            user = "ubuntu"
        elif "debian" in name:
            user = "debian"
        elif "centos" in name:
            user = "centos"
        _TEMPLATE_USER_CACHE[template_id] = user
    except Exception as e:
        print(f"DEBUG: Could not check SSH user for template {template_id}, default to root: {e}")
    return user
