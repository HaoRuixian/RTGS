"""Unit tests for network and serial stream adapters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import serial

from core.ntrip_client import DEFAULT_SOCKET_TIMEOUT_SECONDS, NtripClient
from core.serial_client import SerialClient


class _FakeSocket:
    def __init__(self, responses: list[bytes], *, connect_error: OSError | None = None) -> None:
        self.responses = iter(responses)
        self.connect_error = connect_error
        self.timeout: float | None = None
        self.address: tuple[str, int] | None = None
        self.sent = b""
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple[str, int]) -> None:
        self.address = address
        if self.connect_error is not None:
            raise self.connect_error

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _size: int) -> bytes:
        return next(self.responses, b"")

    def close(self) -> None:
        self.closed = True


class _FakeSerial:
    def __init__(self) -> None:
        self.is_open = True
        self.writes: list[bytes] = []

    def close(self) -> None:
        self.is_open = False

    def read(self, size: int) -> bytes:
        return b"data"[:size]

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)


@pytest.mark.unit
def test_ntrip_client_sends_authenticated_request(monkeypatch) -> None:
    fake_socket = _FakeSocket([b"ICY 200 OK\r\n"])
    monkeypatch.setattr("core.ntrip_client.socket.socket", lambda *_args: fake_socket)
    client = NtripClient("caster.example", 2101, "MOUNT", "user", "password")

    connected = client.connect()

    assert connected is fake_socket
    assert fake_socket.timeout == DEFAULT_SOCKET_TIMEOUT_SECONDS
    assert fake_socket.address == ("caster.example", 2101)
    assert fake_socket.sent.startswith(b"GET /MOUNT HTTP/1.0\r\n")
    assert b"Authorization: Basic " in fake_socket.sent
    assert b"password" not in fake_socket.sent


@pytest.mark.unit
@pytest.mark.parametrize(
    "response, connect_error",
    [(b"HTTP/1.0 401 Unauthorized\r\n", None), (b"", OSError("offline"))],
)
def test_ntrip_client_closes_rejected_or_failed_connections(
    monkeypatch, response: bytes, connect_error: OSError | None
) -> None:
    fake_socket = _FakeSocket([response], connect_error=connect_error)
    monkeypatch.setattr("core.ntrip_client.socket.socket", lambda *_args: fake_socket)
    client = NtripClient("caster.example", 2101, "MOUNT", "user", "password")

    assert client.connect() is None
    assert fake_socket.closed is True
    assert client.sock is None


@pytest.mark.unit
def test_serial_client_maps_configuration_and_delegates_io(monkeypatch) -> None:
    fake_serial = _FakeSerial()
    captured: dict[str, object] = {}

    def open_serial(**kwargs):
        captured.update(kwargs)
        return fake_serial

    monkeypatch.setattr("core.serial_client.serial.Serial", open_serial)
    client = SerialClient(
        "/dev/ttyUSB0",
        baudrate=230400,
        databits=7,
        stopbits=1.5,
        parity="Even",
        flowctrl="RTS/CTS",
        timeout=2.5,
    )

    assert client.connect() is fake_serial
    assert captured["port"] == "/dev/ttyUSB0"
    assert captured["bytesize"] == serial.SEVENBITS
    assert captured["stopbits"] == serial.STOPBITS_ONE_POINT_FIVE
    assert captured["parity"] == serial.PARITY_EVEN
    assert captured["rtscts"] is True
    assert captured["xonxoff"] is False
    assert client.read(2) == b"da"
    assert client.write(b"rtcm") == 4

    client.close()
    assert client.ser is None
    with pytest.raises(ConnectionError, match="not open"):
        client.read()


@pytest.mark.unit
def test_serial_client_from_config_preserves_legacy_fields(monkeypatch) -> None:
    settings = SimpleNamespace(
        source_type="Serial Port",
        serial_port="COM7",
        baudrate=115200,
        databits=8,
        stopbits=2,
        parity="Odd",
        flowctrl="XOn/XOff",
        timeout=3.0,
    )
    monkeypatch.setattr("core.global_config.get_connection_settings", lambda _stream: settings)

    client = SerialClient.from_config("EPH")

    assert client.port == "COM7"
    assert client.stopbits == 2
    assert client.parity == "Odd"
    assert client.flowctrl == "XOn/XOff"
    assert client.timeout == 3.0


@pytest.mark.unit
def test_serial_client_normalizes_missing_write_count() -> None:
    fake_serial = _FakeSerial()
    fake_serial.write = lambda _data: None
    client = SerialClient("COM7")
    client.ser = fake_serial

    assert client.write(b"rtcm") == 0


@pytest.mark.unit
def test_serial_client_from_config_rejects_non_serial_source(monkeypatch) -> None:
    settings = SimpleNamespace(source_type="NTRIP Server")
    monkeypatch.setattr("core.global_config.get_connection_settings", lambda _stream: settings)

    with pytest.raises(ValueError, match="source type is not Serial Port"):
        SerialClient.from_config()
