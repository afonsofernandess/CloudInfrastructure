import os
import sys

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.containers.docker_client import list_containers

def print_containers():
    print("Listing containers for user 'angie':")
    try:
        containers = list_containers("angie")
        print(f"Found {len(containers)} containers:")
        for c in containers:
            print(f"  - ID: {c['container_id']}, Name: {c['name']}, Image: {c['image']}, Status: {c['status']}, VM: {c['vm_id']}")
    except Exception as e:
        print(f"Error listing containers: {e}")

if __name__ == "__main__":
    print_containers()
