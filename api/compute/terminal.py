import asyncio
import paramiko
from fastapi import APIRouter, WebSocket
import os
# pip install python-dotenv
from dotenv import load_dotenv

router = APIRouter(prefix="/terminal", tags=["terminal"])
load_dotenv()
# NOW USING THE SSH TUNNEL
GATEWAY_IP = os.getenv("GATEWAY_IP")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT"))
GATEWAY_USER = os.getenv("GATEWAY_USER")
GATEWAY_PASSWORD = os.getenv("GATEWAY_PASSWORD") # <-- STILL NEED YOUR PASSWORD HERE

@router.websocket("/{vm_ip}")
async def vm_terminal(websocket: WebSocket, vm_ip: str):
    await websocket.accept()
    
    gateway_client = paramiko.SSHClient()
    gateway_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    vm_client = paramiko.SSHClient()
    vm_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 1. Connect to Gateway (PonchaLaptop)
        print(f"DEBUG: Connecting to Gateway {GATEWAY_USER}@{GATEWAY_IP}:{GATEWAY_PORT}...")
        gateway_client.connect(
            GATEWAY_IP, 
            port=GATEWAY_PORT, 
            username=GATEWAY_USER, 
            password=GATEWAY_PASSWORD,
            timeout=10
        )
        
        # 2. Open a tunnel (direct-tcpip) to the VM's port 22
        transport = gateway_client.get_transport()
        vm_channel = transport.open_channel(
            "direct-tcpip", 
            (vm_ip, 22), 
            (GATEWAY_IP, 0)
        )
        
        # 3. Connect to the VM *through* the tunnel
        # Determine the correct SSH user by checking template type
        ssh_user = "root"
        try:
            from api.database import SessionLocal
            from api.compute.models import VMInstance
            from opennebula.vm_manager import list_all_vms, get_ssh_user_by_template
            
            db_sess = SessionLocal()
            try:
                one_vm_id = None
                for vm in list_all_vms():
                    if vm.get("ip_address") == vm_ip:
                        one_vm_id = vm["one_vm_id"]
                        break
                
                if one_vm_id is not None:
                    inst = db_sess.query(VMInstance).filter(VMInstance.one_vm_id == one_vm_id).first()
                    if inst:
                        ssh_user = get_ssh_user_by_template(inst.template_id)
            finally:
                db_sess.close()
        except Exception as e:
            print(f"DEBUG: Could not automatically detect SSH user for terminal IP {vm_ip}: {e}")

        print(f"DEBUG: Connecting to VM {vm_ip} via tunnel as user '{ssh_user}'...")
        
        # Look for default private keys on your Mac
        home = os.path.expanduser("~")
        possible_keys = [
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "id_dsa"),
        ]
        
        vm_client.connect(
            vm_ip,
            username=ssh_user,
            sock=vm_channel,
            timeout=10,
            key_filename=[k for k in possible_keys if os.path.exists(k)],
            allow_agent=True
        )
        
        # 4. Start the interactive shell on the VM
        channel = vm_client.invoke_shell(term='xterm', width=80, height=24)
        channel.setblocking(False)

        async def b_to_ws():
            while True:
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096).decode('utf-8', errors='ignore')
                        await websocket.send_text(data)
                    await asyncio.sleep(0.02)
                except Exception: break
        async def ws_to_b():
            while True:
                try:
                    data = await websocket.receive_text()
                    channel.send(data)
                except Exception: break
        
        print(f"DEBUG: Terminal session started for {vm_ip}")
        await asyncio.gather(b_to_ws(), ws_to_b())

    except Exception as e:
        await websocket.send_text(f"\r\n\x1b[1;31m[Error] Terminal Bridge Failed: {e}\x1b[0m\r\n")
        print(f"ERROR: {e}")
    finally:
        vm_client.close()
        gateway_client.close()
        try:
            await websocket.close()
        except: pass
