"""NTRIP caster socket 客户端。"""

import base64
import logging
import socket

LOGGER = logging.getLogger(__name__)
DEFAULT_SOCKET_TIMEOUT_SECONDS = 10.0


class NtripClient:
    """
    基于 socket 的轻量 NTRIP 客户端。

    Args:
        host: NTRIP caster 主机名或 IP。
        port: NTRIP caster 端口。
        mountpoint: 挂载点名称。
        user: 认证用户名。
        password: 认证密码。
    """

    def __init__(
        self,
        host: str,
        port: int,
        mountpoint: str,
        user: str,
        password: str,
    ) -> None:
        self.host = host
        self.port = port
        self.mountpoint = mountpoint
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.sock: socket.socket | None = None

    def connect(self) -> socket.socket | None:
        """
        建立 TCP 连接并发送 NTRIP GET 请求。

        Returns:
            连接成功时返回可读 socket；连接失败时返回 None。
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(DEFAULT_SOCKET_TIMEOUT_SECONDS)
            self.sock.connect((self.host, self.port))

            headers = (
                f"GET /{self.mountpoint} HTTP/1.0\r\n"
                f"User-Agent: NTRIP Python/GNSS-IR\r\n"
                f"Authorization: Basic {self.auth}\r\n"
                f"\r\n"
            )
            self.sock.sendall(headers.encode())

            response = b""
            while b"\n" not in response:
                chunk = self.sock.recv(1024)
                if not chunk:
                    raise ConnectionError("Server closed connection.")
                response += chunk

            LOGGER.debug("NTRIP response header: %s", response.decode(errors="ignore").strip())

            if b"200 OK" in response:
                LOGGER.info("Connected to NTRIP mountpoint %s", self.mountpoint)
                return self.sock

            LOGGER.warning("NTRIP connection rejected: %s", response.decode(errors="ignore").strip())
            self.close()
            return None

        except (OSError, ConnectionError) as exc:
            LOGGER.warning(
                "NTRIP connection error for %s:%s/%s: %s",
                self.host,
                self.port,
                self.mountpoint,
                exc,
            )
            self.close()
            return None

    def close(self) -> None:
        """关闭当前 socket 连接。"""
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError as exc:
                LOGGER.debug("Error while closing NTRIP socket: %s", exc)
            finally:
                self.sock = None
