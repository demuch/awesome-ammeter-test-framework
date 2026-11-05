from socket import socket, AF_INET, SOCK_STREAM

from Ammeters.base_ammeter import ERROR_PREFIX


def request_current_from_ammeter(port: int, command: bytes, timeout: float = 5.0):
    with socket(AF_INET, SOCK_STREAM) as s:
        # Without a timeout recv() blocks forever if the peer never answers
        s.settimeout(timeout)
        s.connect(('localhost', port))
        s.sendall(command)
        data = s.recv(1024)
        if not data:
            print("No data received.")
        elif data.startswith(ERROR_PREFIX):
            print(f"Ammeter on port {port} returned an error: {data.decode('utf-8')}")
        else:
            print(f"Received current measurement from port {port}: {data.decode('utf-8')} A")

