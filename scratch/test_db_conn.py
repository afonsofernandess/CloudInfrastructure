import docker

try:
    client = docker.DockerClient(base_url="ssh://root@172.16.100.2", use_ssh_client=True)
    container = client.containers.get("db-angie-hello")
    print(f"Container '{container.name}' is in status: {container.status}")
    
    # Run pg_isready command inside the database container
    exit_code, output = container.exec_run("pg_isready -U angie -d hello")
    print(f"\npg_isready exit code: {exit_code}")
    print(f"pg_isready output: {output.decode('utf-8').strip()}")
    
    if exit_code == 0:
        print("[SUCCESS] The database is online, running, and accepting connections!")
    else:
        print("[FAIL] The database is not accepting connections.")
except Exception as e:
    print(f"Error checking database container: {e}")
