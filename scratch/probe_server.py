import urllib.request
import urllib.error

def probe():
    print("Probing http://localhost:8000/...")
    try:
        response = urllib.request.urlopen("http://localhost:8000/", timeout=5)
        print(f"Success! Status code: {response.status}")
        print("Response body:")
        print(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Failed to connect: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    probe()
