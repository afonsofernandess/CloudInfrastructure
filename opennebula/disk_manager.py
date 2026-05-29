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


def attach_disk(one_vm_id: int, one_image_id: int) -> None:
    """Attach an image to a running VM as a disk."""
    client = get_client()
    client.vm.attach(one_vm_id, f'DISK=[IMAGE_ID="{one_image_id}"]')


def detach_disk(one_vm_id: int, disk_index: int) -> None:
    """Detach a disk index from a running VM."""
    client = get_client()
    client.vm.detach(one_vm_id, disk_index)


def get_attached_vm_and_disk_index(username: str, one_image_id: int) -> tuple:
    """
    Find which of the user's active VMs this image/disk is attached to,
    and return (one_vm_id, disk_index). Returns (None, None) if not attached.
    """
    from api.database import SessionLocal
    from api.auth.models import User
    from api.compute.models import VMInstance

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return None, None
        instances = db.query(VMInstance).filter(
            VMInstance.user_id == user.id,
            VMInstance.terminated_at == None
        ).all()
    finally:
        db.close()

    client = get_client()
    for inst in instances:
        try:
            vm_info = client.vm.info(inst.one_vm_id)
            disks = vm_info.TEMPLATE.get("DISK", [])
            if not isinstance(disks, list):
                disks = [disks]
            for d in disks:
                img_id = d.get("IMAGE_ID")
                if img_id and int(img_id) == one_image_id:
                    return inst.one_vm_id, int(d.get("DISK_ID"))
        except Exception:
            continue
    return None, None

