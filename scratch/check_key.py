import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opennebula.connection import get_client

def check_all_users():
    client = get_client()
    try:
        user_pool = client.userpool.info()
        for u in user_pool.USER:
            user_info = client.user.info(u.ID)
            print(f"User: {user_info.NAME} (ID: {user_info.ID})")
            if hasattr(user_info, 'TEMPLATE'):
                print(f"  Template keys: {list(user_info.TEMPLATE.keys())}")
                key = user_info.TEMPLATE.get('SSH_PUBLIC_KEY')
                if key:
                    print(f"  SSH_PUBLIC_KEY found: {key[:30]}...")
                else:
                    print("  SSH_PUBLIC_KEY NOT FOUND")
            else:
                print("  No TEMPLATE")
            print("-" * 20)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_all_users()
