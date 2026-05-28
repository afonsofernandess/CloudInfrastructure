import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opennebula.connection import get_client

def main():
    client = get_client()
    try:
        print("Available client.vm methods:")
        methods = dir(client.vm)
        for m in sorted(methods):
            if not m.startswith("_"):
                print(f"  - vm.{m}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
