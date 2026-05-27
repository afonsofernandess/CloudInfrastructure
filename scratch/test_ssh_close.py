import docker
import gc
import sys

# Test client creation and closing WITHOUT clearing adapters
try:
    ip = "172.16.100.3" 
    print(f"Connecting to {ip}...")
    client = docker.DockerClient(base_url=f"ssh://root@{ip}", use_ssh_client=True)
    print("Version:", client.version())
    client.close()
    
    print("Client closed. Running GC...")
    gc.collect()
    print("GC completed successfully.")
except Exception as e:
    print("Error:", e)
