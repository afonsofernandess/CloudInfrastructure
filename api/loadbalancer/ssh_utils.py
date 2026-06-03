import os
import logging
import paramiko
from dotenv import load_dotenv

log = logging.getLogger("loadbalancer.ssh_utils")


def run_ssh_command(ip: str, command: str, ssh_user: str = "root", timeout: int = 120) -> str:
    """Execute a shell command on a target VM by tunneling through the SSH Gateway.
    Raises RuntimeError if the command exits with a non-zero status.
    """
    load_dotenv()
    gw_ip = os.getenv("GATEWAY_IP")
    gw_port = int(os.getenv("GATEWAY_PORT", "22"))
    gw_user = os.getenv("GATEWAY_USER")
    gw_pass = os.getenv("GATEWAY_PASSWORD")

    if not gw_ip or not gw_user:
        raise RuntimeError("Gateway configuration is missing from environment variables.")

    gateway_client = paramiko.SSHClient()
    gateway_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    vm_client = paramiko.SSHClient()
    vm_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        gateway_client.connect(gw_ip, port=gw_port, username=gw_user, password=gw_pass, timeout=10)
        transport = gateway_client.get_transport()
        vm_channel = transport.open_channel("direct-tcpip", (ip, 22), (gw_ip, 0))
        
        home = os.path.expanduser("~")
        possible_keys = [
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "id_dsa"),
        ]
        
        vm_client.connect(
            ip,
            username=ssh_user,
            sock=vm_channel,
            timeout=15,
            key_filename=[k for k in possible_keys if os.path.exists(k)],
            allow_agent=True
        )
        
        stdin, stdout, stderr = vm_client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8")
        err = stderr.read().decode("utf-8")

        if err:
            log.debug("SSH command stderr on %s: %s", ip, err.strip())

        if exit_code != 0:
            raise RuntimeError(
                f"SSH command failed on {ip} (exit {exit_code}):\n"
                f"  CMD: {command}\n"
                f"  STDERR: {err.strip()}"
            )
            
        return out
    finally:
        vm_client.close()
        gateway_client.close()


def write_ssh_file(ip: str, file_path: str, content: str, ssh_user: str = "root"):
    """Write content to a file on a target VM by tunneling through the SSH Gateway."""
    load_dotenv()
    gw_ip = os.getenv("GATEWAY_IP")
    gw_port = int(os.getenv("GATEWAY_PORT", "22"))
    gw_user = os.getenv("GATEWAY_USER")
    gw_pass = os.getenv("GATEWAY_PASSWORD")

    if not gw_ip or not gw_user:
        raise RuntimeError("Gateway configuration is missing from environment variables.")

    gateway_client = paramiko.SSHClient()
    gateway_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    vm_client = paramiko.SSHClient()
    vm_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        gateway_client.connect(gw_ip, port=gw_port, username=gw_user, password=gw_pass, timeout=10)
        transport = gateway_client.get_transport()
        vm_channel = transport.open_channel("direct-tcpip", (ip, 22), (gw_ip, 0))
        
        home = os.path.expanduser("~")
        possible_keys = [
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "id_dsa"),
        ]
        
        vm_client.connect(
            ip,
            username=ssh_user,
            sock=vm_channel,
            timeout=15,
            key_filename=[k for k in possible_keys if os.path.exists(k)],
            allow_agent=True
        )
        
        sftp = vm_client.open_sftp()
        try:
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                try:
                    sftp.mkdir(parent_dir)
                except Exception:
                    pass
            with sftp.file(file_path, "w") as f:
                f.write(content)
        finally:
            sftp.close()
    finally:
        vm_client.close()
        gateway_client.close()
