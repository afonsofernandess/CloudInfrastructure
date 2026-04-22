"""
Keeps our local users in sync with OpenNebula users.
When a user registers/updates/deletes on our platform,
the same action is mirrored to OpenNebula.
"""

from opennebula.connection import get_client


def create_one_user(username: str, password: str) -> int:
    """
    Create a user in OpenNebula and return their OpenNebula user ID.
    Group 1 = 'users' (default unprivileged group).
    """
    client = get_client()
    one_user_id = client.user.allocate(username, password, "core", [1])
    return one_user_id


def update_one_user_password(one_user_id: int, new_password: str) -> None:
    """Update a user's password in OpenNebula."""
    client = get_client()
    client.user.passwd(one_user_id, new_password)


def delete_one_user(one_user_id: int) -> None:
    """Delete a user from OpenNebula."""
    client = get_client()
    client.user.delete(one_user_id)
