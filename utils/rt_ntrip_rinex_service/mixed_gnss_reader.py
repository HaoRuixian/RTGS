"""
Mixed GNSS stream reader for serial links carrying RTCM and UBX messages.

This reader exists to preserve the current RTCM processing pipeline while
adding a narrow UBX-RXM-SFRBX decode path for SBAS raw navigation messages.
The SBAS raw frames are converted into a lightweight Python message object
which carries the SBAS fields needed to build Cartesian ephemeris records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from socket import socket

from pynmeagps import SocketWrapper
from pyrtcm import RTCMReader

from .gnss_time import GNSSTime
from .unicore import (
    UNICORE_BINARY_HEADER_LENGTH,
    UNICORE_BINARY_SYNC,
    UnicoreMessage,
    UnicoreParseError,
)


RTCM_PREAMBLE = 0xD3
UBX_SYNC1 = 0xB5
UBX_SYNC2 = 0x62
UBX_CLASS_RXM = 0x02
UBX_ID_RXM_SFRBX = 0x13


def getbitu(buff: bytes, pos: int, length: int) -> int:
    """Extract unsigned bits using MSB-first numbering."""
    bits = 0
    for i in range(pos, pos + length):
        bits = (bits << 1) | ((buff[i // 8] >> (7 - i % 8)) & 1)
    return bits


def setbitu(buff: bytearray, pos: int, length: int, value: int) -> None:
    """Set unsigned bits using MSB-first numbering."""
    for i in range(length):
        bit = (value >> (length - 1 - i)) & 1
        idx = pos + i
        mask = 1 << (7 - idx % 8)
        if bit:
            buff[idx // 8] |= mask
        else:
            buff[idx // 8] &= (~mask) & 0xFF


@dataclass
class SBASRawMessage:
    """Minimal SBAS raw navigation message for type-9 decoding."""

    prn: int
    week: int
    tow: int
    msg: bytes
    source: str = "UBX-RXM-SFRBX"
    protocol: str = "UBX"
    sbas_type: int = field(init=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        self.sbas_type = getbitu(self.msg, 8, 6)
        self.identity = f"SBAS_RAW_{self.sbas_type}"


class MixedGNSSReader:
    """
    Read a byte stream containing RTCM3 and UBX messages.

    RTCM frames are parsed with pyrtcm. UBX frames are ignored except for
    UBX-RXM-SFRBX SBAS/QZSS-L1S raw navigation pages, which are converted into
    ``SBASRawMessage`` instances.
    """

    def __init__(self, datastream):
        if isinstance(datastream, socket):
            self._stream = SocketWrapper(datastream, bufsize=4096)
        else:
            self._stream = datastream

    def __iter__(self):
        return self

    def __next__(self):
        raw, msg = self.read()
        if raw is None and msg is None:
            raise StopIteration
        return raw, msg

    def read(self):
        while True:
            try:
                prefix = self._read_bytes(1)
            except EOFError:
                return None, None

            if prefix[0] == RTCM_PREAMBLE:
                try:
                    raw, msg = self._read_rtcm(prefix)
                except EOFError:
                    return None, None
                return raw, msg

            if prefix[0] == ord("#"):
                raw, msg = self._read_unicore_ascii(prefix)
                if msg is None:
                    continue
                return raw, msg

            if prefix[0] == UNICORE_BINARY_SYNC[0]:
                try:
                    raw, msg = self._read_unicore_binary(prefix)
                except EOFError:
                    return None, None
                if raw is None and msg is None:
                    continue
                return raw, msg

            if prefix[0] == UBX_SYNC1:
                try:
                    sync2 = self._read_bytes(1)
                except EOFError:
                    return None, None
                if sync2[0] != UBX_SYNC2:
                    continue

                try:
                    raw, msg = self._read_ubx(prefix + sync2)
                except EOFError:
                    return None, None
                if raw is None and msg is None:
                    continue
                return raw, msg

    def _read_rtcm(self, prefix: bytes):
        hdr = self._read_bytes(2)
        size = ((hdr[0] & 0x03) << 8) | hdr[1]
        payload = self._read_bytes(size)
        crc = self._read_bytes(3)
        raw = prefix + hdr + payload + crc
        try:
            msg = RTCMReader.parse(raw)
        except Exception:
            msg = None
        return raw, msg

    def _read_unicore_ascii(self, prefix: bytes):
        line = bytearray(prefix)
        while True:
            try:
                chunk = self._read_bytes(1)
            except EOFError:
                break
            line.extend(chunk)
            if chunk == b"\n":
                break

        raw = bytes(line)
        try:
            msg = UnicoreMessage.parse_ascii(raw)
        except UnicoreParseError:
            msg = None
        return raw, msg

    def _read_unicore_binary(self, prefix: bytes):
        sync_tail = self._read_bytes(2)
        sync = prefix + sync_tail
        if sync != UNICORE_BINARY_SYNC:
            return None, None

        header_tail = self._read_bytes(UNICORE_BINARY_HEADER_LENGTH - len(sync))
        header = sync + header_tail
        size = int.from_bytes(header[6:8], "little")
        body = self._read_bytes(size)
        crc = self._read_bytes(4)
        raw = header + body + crc
        try:
            msg = UnicoreMessage.parse_binary(raw)
        except UnicoreParseError:
            msg = None
        return raw, msg

    def _read_ubx(self, sync: bytes):
        hdr = self._read_bytes(4)
        msg_class = hdr[0]
        msg_id = hdr[1]
        payload_len = hdr[2] | (hdr[3] << 8)
        payload = self._read_bytes(payload_len)
        checksum = self._read_bytes(2)
        raw = sync + hdr + payload + checksum

        if self._ubx_checksum(raw[2:-2]) != checksum:
            return None, None

        if msg_class == UBX_CLASS_RXM and msg_id == UBX_ID_RXM_SFRBX:
            return raw, self._parse_rxm_sfrbx(payload)

        return raw, None

    def _parse_rxm_sfrbx(self, payload: bytes):
        if len(payload) < 8:
            return None

        gnss_id = payload[0]
        sv_id = payload[1]
        sig_id = payload[2]
        num_words = payload[4]

        if len(payload) < 8 + num_words * 4:
            return None

        # u-blox reports SBAS L1C/A as gnssId=1 and QZSS L1S with the same
        # 250-bit page layout as SBAS and shares the same navigation decoder.
        if gnss_id == 1:
            prn = sv_id
        elif gnss_id == 5 and sig_id == 1:
            prn = sv_id + 182
        else:
            return None

        if num_words < 8:
            return None

        words = [
            int.from_bytes(payload[8 + i * 4 : 12 + i * 4], "little")
            for i in range(8)
        ]
        buff = bytearray(32)
        for i, word in enumerate(words):
            setbitu(buff, 32 * i, 32, word)

        msg_bytes = bytes(buff[:29])
        msg_bytes = msg_bytes[:-1] + bytes([msg_bytes[-1] & 0xC0])

        recv_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        week, tow = GNSSTime.utc_to_gps(recv_time)
        return SBASRawMessage(
            prn=prn,
            week=week,
            tow=int(tow),
            msg=msg_bytes,
        )

    @staticmethod
    def _ubx_checksum(data: bytes) -> bytes:
        ck_a = 0
        ck_b = 0
        for value in data:
            ck_a = (ck_a + value) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return bytes((ck_a, ck_b))

    def _read_bytes(self, size: int) -> bytes:
        if size <= 0:
            return b""
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._stream.read(size - len(chunks))
            if not chunk:
                raise EOFError()
            chunks.extend(chunk)
        return bytes(chunks)
