from opennebula.connection import get_client

def create_disk(name: str, size_gb: int, one_user_id: int) -> int:
    """
    Allocate a new DATABLOCK image of size_gb on the default datastore (ID 1).
    And chown it to the user.
    """
    client = get_client()
    size_mb = size_gb * 1024
    
    # Template definition for empty datablock image
    template = (
        f'NAME="{name}"\n'
        f'TYPE="DATABLOCK"\n'
        f'SIZE="{size_mb}"\n'
        f'DESCRIPTION="Custom user disk volume"\n'
    )
    
    # Datastore ID 1 is the default image datastore
    one_image_id = client.image.allocate(template, 1)
    
    # Chown to the user's OpenNebula ID so they own it
    client.image.chown(one_image_id, one_user_id, -1)
    
    return one_image_id


def delete_disk(one_image_id: int) -> None:
    """Delete a disk image from OpenNebula."""
    client = get_client()
    client.image.delete(one_image_id)


def get_disk_status(one_image_id: int) -> str:
    """Get the live status of an image."""
    client = get_client()
    try:
        info = client.image.info(one_image_id)
        # Image states:
        # 0: INIT, 1: READY, 2: USED, 3: DISABLED, 4: LOCKED, 5: ERROR, 6: CLONE, 7: DELETE, 8: USED_PERS
        states = {
            0: "INIT",
            1: "READY",
            2: "USED",
            3: "DISABLED",
            4: "LOCKED",
            5: "ERROR",
            6: "CLONE",
            7: "DELETE",
            8: "USED_PERS"
        }
        return states.get(info.STATE, "UNKNOWN")
    except Exception:
        return "UNKNOWN"
