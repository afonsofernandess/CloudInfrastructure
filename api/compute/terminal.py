import asyncio
import paramiko
from fastapi import APIRouter, WebSocket

router = APIRouter(prefix="/terminal", tags=["terminal"])

# NOW USING THE SSH TUNNEL
GATEWAY_IP = "127.0.0.1" 
GATEWAY_PORT = 2222
GATEWAY_USER = "angelo"
GATEWAY_PASSWORD = "ronaldo1" # <-- STILL NEED YOUR PASSWORD HERE

@router.websocket("/{vm_ip}")
async def vm_terminal(websocket: WebSocket, vm_ip: str):
    await websocket.accept()
    
    gateway_client = paramiko.SSHClient()
    gateway_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 1. Connect to Gateway via the tunnel (localhost:2222)
        print(f"DEBUG: Connecting to Gateway as user '{GATEWAY_USER}' via localhost:{GATEWAY_PORT}...")
        
        def gateway_handler(title, instructions, prompt_list):
            return [GATEWAY_PASSWORD] * len(prompt_list)

        try:
            gateway_client.connect(
                GATEWAY_IP, 
                port=GATEWAY_PORT, 
                username=GATEWAY_USER, 
                password=GATEWAY_PASSWORD, 
                timeout=15,
                allow_agent=True
            )
        except paramiko.ssh_exception.AuthenticationException:
            print("DEBUG: Gateway password auth failed, trying interactive...")
            gateway_client.get_transport().auth_interactive(GATEWAY_USER, gateway_handler)
        
        # Start a full interactive shell on the gateway
        print(f"DEBUG: Starting interactive shell on gateway...")
        channel = gateway_client.invoke_shell(term='xterm', width=80, height=24)
        channel.setblocking(False)

        # Send the SSH command to the shell
        print(f"DEBUG: Sending SSH command to VM {vm_ip}...")
        channel.send(f"ssh -o StrictHostKeyChecking=no root@{vm_ip}\n")

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

        await asyncio.gather(b_to_ws(), ws_to_b())

    except Exception as e:
        await websocket.send_text(f"\r\n\x1b[1;31m[Error] Terminal Bridge Failed: {e}\x1b[0m\r\n")
        print(f"ERROR: {e}")
    finally:
        gateway_client.close()
        try:
            await websocket.close()
        except:
            pass
