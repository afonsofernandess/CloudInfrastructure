import os
import sys
import sqlite3
import paramiko

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import SessionLocal
from api.compute.models import VMInstance
from opennebula.vm_manager import get_vm

def diagnose():
    print("Fetching active VM instances from database...")
    db = SessionLocal()
    instances = db.query(VMInstance).filter(VMInstance.terminated_at == None).all()
    print(f"Found {len(instances)} non-terminated VM instances in DB.")
    
    for inst in instances:
        print(f"\nVM ID: {inst.id}, OpenNebula ID: {inst.one_vm_id}, Name: {inst.name}")
        try:
            live = get_vm(inst.one_vm_id)
            print(f"  OpenNebula state: {live['state']}, LCM state: {live['lcm_state']}, IP: {live['ip_address']}")
            ip = live['ip_address']
            if ip and ip != "—":
                print(f"  Attempting SSH to root@{ip} via Gateway...")
                # We need to jump through the gateway
                # The gateway is configured in ~/.ssh/config for 172.16.100.*, so we can use paramiko with ProxyCommand
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Check if we can connect
                try:
                    # Paramiko can automatically use ~/.ssh/config proxy jump if we configure it, or we can just try connecting
                    # Let's read ~/.ssh/config if paramiko supports it, or use ProxyCommand
                    ssh_config = paramiko.SSHConfig()
                    user_config_file = os.path.expanduser("~/.ssh/config")
                    if os.path.exists(user_config_file):
                        with open(user_config_file) as f:
                            ssh_config.parse(f)
                    
                    host_info = ssh_config.lookup(ip)
                    sock = None
                    if 'proxyjump' in host_info or 'proxycommand' in host_info:
                        print("  Using SSH Proxy config...")
                        # Since standard paramiko SSHClient doesn't automatically do ProxyJump, we can construct the gateway tunnel manually
                        # Let's parse .env for gateway credentials
                        from dotenv import load_dotenv
                        load_dotenv()
                        gw_ip = os.getenv("GATEWAY_IP", "ponchalaptop")
                        gw_port = int(os.getenv("GATEWAY_PORT", "22"))
                        gw_user = os.getenv("GATEWAY_USER", "angelo")
                        gw_pass = os.getenv("GATEWAY_PASSWORD")
                        
                        print(f"  Connecting to Gateway {gw_user}@{gw_ip}:{gw_port}...")
                        gw_transport = paramiko.Transport((gw_ip, gw_port))
                        gw_transport.connect(username=gw_user, password=gw_pass)
                        
                        print(f"  Opening direct-tcpip channel to {ip}:22...")
                        dest_addr = (ip, 22)
                        local_addr = ('localhost', 0)
                        channel = gw_transport.open_channel("direct-tcpip", dest_addr, local_addr)
                        
                        ssh.connect(ip, username="root", sock=channel, timeout=10)
                    else:
                        ssh.connect(ip, username="root", timeout=10)
                    
                    print("  [SUCCESS] Connected to VM SSH!")
                    
                    # 1. Check docker binary
                    stdin, stdout, stderr = ssh.exec_command("which docker")
                    docker_path = stdout.read().decode().strip()
                    print(f"  Docker path: '{docker_path}'")
                    
                    # 2. Check docker service status
                    stdin, stdout, stderr = ssh.exec_command("rc-status --all")
                    print("  rc-status output:")
                    print(stdout.read().decode())
                    
                    # 3. Check service docker status
                    stdin, stdout, stderr = ssh.exec_command("service docker status")
                    print("  service docker status:")
                    print(stdout.read().decode())
                    print(stderr.read().decode())
                    
                    # 4. Check docker daemon logs or process
                    stdin, stdout, stderr = ssh.exec_command("ps aux | grep docker")
                    print("  Docker processes:")
                    print(stdout.read().decode())
                    
                    # 5. Check if we can run dockerd directly or check openrc logs
                    stdin, stdout, stderr = ssh.exec_command("cat /var/log/messages | grep -i docker")
                    print("  Docker logs in /var/log/messages:")
                    print(stdout.read().decode())
                    
                    # 6. Check /etc/apk/repositories and check if apk add docker failed
                    stdin, stdout, stderr = ssh.exec_command("cat /etc/resolv.conf")
                    print("  resolv.conf content:")
                    print(stdout.read().decode())
                    
                    stdin, stdout, stderr = ssh.exec_command("apk info -e docker")
                    print(f"  apk info -e docker exit code: {stdout.channel.recv_exit_status()}")
                    
                except Exception as conn_err:
                    print(f"  [FAIL] Failed to connect or run diagnostics: {conn_err}")
                finally:
                    ssh.close()
        except Exception as e:
            print(f"  Error checking VM info: {e}")
            
    db.close()

if __name__ == "__main__":
    diagnose()
