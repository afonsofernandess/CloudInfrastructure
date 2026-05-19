import pyone
import os
# pip install python-dotenv
from dotenv import load_dotenv


# OpenNebula connection settings
# Requires SSH tunnel: ssh -L 8080:localhost:80 -L 2633:localhost:2633 ubuntu@[ipaddress]
ONE_ENDPOINT = "http://localhost:2633/RPC2"
# get credentials from .env file
load_dotenv()
ONE_USER = os.getenv("ONE_USER")
ONE_PASSWORD = os.getenv("ONE_PASSWORD")


def get_client() -> pyone.OneServer:
    """Return an authenticated OpenNebula client."""
    return pyone.OneServer(ONE_ENDPOINT, session=f"{ONE_USER}:{ONE_PASSWORD}")
