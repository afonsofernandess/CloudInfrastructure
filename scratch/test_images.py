import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opennebula.connection import get_client

def main():
    client = get_client()
    try:
        print("Allocating a test 100MB datablock image on Datastore 1...")
        template = 'NAME="test_wait_datablock"\nTYPE="DATABLOCK"\nSIZE="100"\n'
        image_id = client.image.allocate(template, 1)
        print(f"Allocated image ID: {image_id}")
        
        # Wait for ready state (1 is READY, 2 is USED, 4 is LOCKED)
        for i in range(20):
            info = client.image.info(image_id)
            print(f"State: {info.STATE} (Type: {type(info.STATE)})")
            if info.STATE == 1:
                print("Image is READY!")
                break
            time.sleep(1)
            
        print("Attempting to delete the image now...")
        client.image.delete(image_id)
        print("Successfully deleted!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
