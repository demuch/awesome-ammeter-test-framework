import socket
import time
import random
from abc import ABC, abstractmethod

NotImplementedErrorMsg = "Subclasses must implement this property."

# Replies that start with this prefix are errors, not measurements
ERROR_PREFIX = b"ERROR"

class AmmeterEmulatorBase(ABC):
    def __init__(self, port: int):
        self.port = port
        random.seed(time.time())  # Seed the random number generator for each instance

    def start_server(self):
        """
        Starts the server to listen for client requests.
        The server will run indefinitely, handling one client request at a time.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Allow immediate restart: without this, bind() fails while old connections sit in TIME_WAIT
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('localhost', self.port))
            s.listen()
            print(f"{self.__class__.__name__} is running on port {self.port}")
            while True:
                conn, addr = s.accept()
                with conn:
                    print(f"Connected by {addr}")
                    # A failure with one client must not stop the server for everyone else
                    try:
                        self._handle_request(conn)
                    except Exception as e:
                        print(f"{self.__class__.__name__}: request from {addr} failed: {e!r}")

    def _handle_request(self, conn: socket.socket):
        """
        Reads one command from the client and sends the reply: the measured current for the
        expected command, or an ERROR reply for anything else.

        Args:
            conn: Socket of the accepted client connection.

        Raises:
            OSError: If the client disconnects while the reply is being sent.
                start_server() catches it so the server keeps running.
        """
        data = conn.recv(1024)
        if not data:
            return  # Client closed the connection without sending a command
        if data == self.get_current_command:
            # Call the specific measure_current() method defined in subclasses
            current = self.measure_current()
            conn.sendall(str(current).encode('utf-8'))
        else:
            print(f"{self.__class__.__name__}: unknown command {data!r}")
            conn.sendall(ERROR_PREFIX + b": unknown command " + repr(data[:100]).encode('utf-8'))

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

