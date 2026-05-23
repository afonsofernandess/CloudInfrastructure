import docker
import sys

try:
    client = docker.DockerClient(base_url="ssh://root@172.16.100.2", use_ssh_client=True)
    containers = client.containers.list(all=True)
    print(f"Found {len(containers)} containers:")
    for c in containers:
        print(f"\nID: {c.short_id} | Name: {c.name} | Image: {c.image.tags} | Status: {c.status}")
        try:
            logs = c.logs(tail=10).decode('utf-8')
            print("--- Logs (last 10 lines) ---")
            print(logs or "<No logs>")
            print("----------------------------")
        except Exception as e:
            print(f"Could not fetch logs: {e}")
except Exception as e:
    print(f"Error connecting to Docker: {e}")
