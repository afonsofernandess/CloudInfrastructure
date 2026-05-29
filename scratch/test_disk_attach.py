import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opennebula.connection import get_client

def main():
    client = get_client()
    vm_id = 62  # ubuntu-vm
    image_id = 0  # Alpine Linux
    
    try:
        print(f"Fetching VM {vm_id} info...")
        vm = client.vm.info(vm_id)
        
        print("Disks before attach:")
        disks = vm.TEMPLATE.get("DISK", [])
        if not isinstance(disks, list):
            disks = [disks]
        for d in disks:
            print(f"  - Disk ID: {d.get('DISK_ID')} | Image: {d.get('IMAGE')} | Target: {d.get('TARGET')}")
            
        print(f"\nAttaching Image {image_id} to VM {vm_id}...")
        # Pyone call to one.vm.attach
        client.vm.attach(vm_id, f'DISK=[IMAGE_ID="{image_id}"]')
        print("Attach request sent.")
        
        # Wait a bit and inspect VM disks
        print("Waiting 5 seconds for disk attach to process...")
        time.sleep(5)
        
        vm = client.vm.info(vm_id)
        disks = vm.TEMPLATE.get("DISK", [])
        if not isinstance(disks, list):
            disks = [disks]
        
        attached_disk_id = None
        print("Disks after attach:")
        for d in disks:
            print(f"  - Disk ID: {d.get('DISK_ID')} | Image: {d.get('IMAGE')} | Target: {d.get('TARGET')}")
            if d.get("IMAGE") == "Alpine Linux 3.20":
                attached_disk_id = int(d.get("DISK_ID"))
                
        if attached_disk_id is not None:
            print(f"\nDetaching Disk ID {attached_disk_id} from VM {vm_id}...")
            # Pyone call to one.vm.detach
            client.vm.detach(vm_id, attached_disk_id)
            print("Detach request sent.")
        else:
            print("\nCould not find attached disk in template to detach.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
