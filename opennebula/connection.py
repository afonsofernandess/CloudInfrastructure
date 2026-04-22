import pyone

# OpenNebula connection settings
# Requires SSH tunnel: ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[ipaddress]
ONE_ENDPOINT = "http://localhost:2633/RPC2"
ONE_USER = "oneadmin"
ONE_PASSWORD = "xRYVbRZjOf"


def get_client() -> pyone.OneServer:
    """Return an authenticated OpenNebula client."""
    return pyone.OneServer(ONE_ENDPOINT, session=f"{ONE_USER}:{ONE_PASSWORD}")
