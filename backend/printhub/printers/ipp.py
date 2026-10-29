"""Minimal IPP/1.1 client used to query the local CUPS scheduler.

Only the operations the hub needs are implemented (printer attributes,
job attributes, CUPS-Get-Printers). Document submission goes through `lp`
so that CUPS performs its normal option mapping and filtering.
"""
from __future__ import annotations

import http.client
import os
import socket
import struct
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

# Operation ids
GET_PRINTER_ATTRIBUTES = 0x000B
GET_JOB_ATTRIBUTES = 0x0009
GET_JOBS = 0x000A
CUPS_GET_PRINTERS = 0x4002

# Delimiter tags
TAG_OPERATION = 0x01
TAG_JOB = 0x02
TAG_END = 0x03
TAG_PRINTER = 0x04
TAG_UNSUPPORTED_GROUP = 0x05

# Value tags
TAG_UNSUPPORTED = 0x10
TAG_UNKNOWN = 0x12
TAG_NO_VALUE = 0x13
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_OCTET = 0x30
TAG_DATETIME = 0x31
TAG_RESOLUTION = 0x32
TAG_RANGE = 0x33
TAG_BEGIN_COLLECTION = 0x34
TAG_TEXT_LANG = 0x35
TAG_NAME_LANG = 0x36
TAG_END_COLLECTION = 0x37
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49
TAG_MEMBER_NAME = 0x4A

STATUS_OK_MAX = 0x00FF
STATUS_NOT_FOUND = 0x0406


class IppError(Exception):
    """Transport or protocol failure talking to the IPP server."""


@dataclass
class IppResponse:
    status: int
    request_id: int
    groups: list[tuple[int, dict[str, list[Any]]]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status <= STATUS_OK_MAX

    def first(self, group_tag: int) -> dict[str, list[Any]]:
        for tag, attrs in self.groups:
            if tag == group_tag:
                return attrs
        return {}

    def all(self, group_tag: int) -> list[dict[str, list[Any]]]:
        return [attrs for tag, attrs in self.groups if tag == group_tag]


def _encode_attr(tag: int, name: str, values: list[Any]) -> bytes:
    out = bytearray()
    for i, value in enumerate(values):
        key = name.encode() if i == 0 else b""
        if tag in (TAG_INTEGER, TAG_ENUM):
            data = struct.pack(">i", int(value))
        elif tag == TAG_BOOLEAN:
            data = b"\x01" if value else b"\x00"
        else:
            data = str(value).encode("utf-8")
        out += struct.pack(">BH", tag, len(key)) + key + struct.pack(">H", len(data)) + data
    return bytes(out)


def encode_request(op: int, request_id: int, operation_attrs: list[tuple[int, str, list[Any]]]) -> bytes:
    body = bytearray(struct.pack(">BBHI", 1, 1, op, request_id))
    body.append(TAG_OPERATION)
    for tag, name, values in operation_attrs:
        body += _encode_attr(tag, name, values)
    body.append(TAG_END)
    return bytes(body)


def _decode_value(tag: int, data: bytes) -> Any:
    if tag in (TAG_INTEGER, TAG_ENUM):
        return struct.unpack(">i", data)[0] if len(data) == 4 else None
    if tag == TAG_BOOLEAN:
        return bool(data[0]) if data else None
    if tag == TAG_RANGE:
        return tuple(struct.unpack(">ii", data)) if len(data) == 8 else None
    if tag == TAG_RESOLUTION:
        return struct.unpack(">iib", data) if len(data) == 9 else None
    if tag in (TAG_TEXT_LANG, TAG_NAME_LANG):
        if len(data) < 4:
            return ""
        lang_len = struct.unpack(">H", data[:2])[0]
        text_len = struct.unpack(">H", data[2 + lang_len : 4 + lang_len])[0]
        return data[4 + lang_len : 4 + lang_len + text_len].decode("utf-8", "replace")
    if tag == TAG_DATETIME:
        return data.hex()
    if tag in (TAG_UNSUPPORTED, TAG_UNKNOWN, TAG_NO_VALUE):
        return None
    if tag == TAG_OCTET:
        return data.decode("utf-8", "replace")
    return data.decode("utf-8", "replace")


def _read_collection(buf: bytes, pos: int) -> tuple[dict[str, list[Any]], int]:
    """Decode collection members after a begCollection value. Returns (dict, new_pos)."""
    result: dict[str, list[Any]] = {}
    member: str | None = None
    while pos < len(buf):
        tag = buf[pos]
        name_len = struct.unpack(">H", buf[pos + 1 : pos + 3])[0]
        pos += 3 + name_len
        val_len = struct.unpack(">H", buf[pos : pos + 2])[0]
        data = buf[pos + 2 : pos + 2 + val_len]
        pos += 2 + val_len
        if tag == TAG_END_COLLECTION:
            return result, pos
        if tag == TAG_MEMBER_NAME:
            member = data.decode("utf-8", "replace")
            result.setdefault(member, [])
            continue
        if tag == TAG_BEGIN_COLLECTION:
            value, pos = _read_collection(buf, pos)
        else:
            value = _decode_value(tag, data)
        if member is not None:
            result[member].append(value)
    raise IppError("Unterminated collection in IPP response")


def decode_response(buf: bytes) -> IppResponse:
    if len(buf) < 9:
        raise IppError("IPP response too short")
    _major, _minor, status, request_id = struct.unpack(">BBHI", buf[:8])
    resp = IppResponse(status=status, request_id=request_id)
    pos = 8
    current: dict[str, list[Any]] | None = None
    last_name: str | None = None
    try:
        while pos < len(buf):
            tag = buf[pos]
            if tag <= 0x0F:  # delimiter
                pos += 1
                if tag == TAG_END:
                    break
                current = {}
                resp.groups.append((tag, current))
                last_name = None
                continue
            name_len = struct.unpack(">H", buf[pos + 1 : pos + 3])[0]
            name = buf[pos + 3 : pos + 3 + name_len].decode("utf-8", "replace")
            pos += 3 + name_len
            val_len = struct.unpack(">H", buf[pos : pos + 2])[0]
            data = buf[pos + 2 : pos + 2 + val_len]
            pos += 2 + val_len
            if tag == TAG_BEGIN_COLLECTION:
                value, pos = _read_collection(buf, pos)
            else:
                value = _decode_value(tag, data)
            if current is None:
                continue
            if name:
                last_name = name
                current[name] = [value]
            elif last_name is not None:
                current[last_name].append(value)
    except (struct.error, IndexError) as exc:
        raise IppError(f"Malformed IPP response: {exc}") from exc
    return resp


DEFAULT_SOCKETS = ("/run/cups/cups.sock", "/var/run/cups/cups.sock", "/private/var/run/cupsd")


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def find_cups_socket() -> str | None:
    for path in DEFAULT_SOCKETS:
        if os.path.exists(path):
            return path
    return None


class IppClient:
    """Talks to CUPS over its Unix domain socket when available, else TCP."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 631,
        timeout: float = 5.0,
        user: str = "printhub",
        socket_path: str | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.user = user
        self.socket_path = socket_path
        self._request_id = 0

    @property
    def endpoint(self) -> str:
        return self.socket_path or f"{self.host}:{self.port}"

    def _connection(self) -> http.client.HTTPConnection:
        if self.socket_path:
            return _UnixHTTPConnection(self.socket_path, self.timeout)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _next_id(self) -> int:
        self._request_id = (self._request_id % 0x7FFFFFFF) + 1
        return self._request_id

    def _base_attrs(self) -> list[tuple[int, str, list[Any]]]:
        return [
            (TAG_CHARSET, "attributes-charset", ["utf-8"]),
            (TAG_LANGUAGE, "attributes-natural-language", ["en"]),
        ]

    def printer_uri(self, queue: str) -> str:
        return f"ipp://{self.host}:{self.port}/printers/{quote(queue, safe='')}"

    def request(self, path: str, op: int, attrs: list[tuple[int, str, list[Any]]]) -> IppResponse:
        body = encode_request(op, self._next_id(), self._base_attrs() + attrs)
        conn = self._connection()
        try:
            conn.request("POST", path, body=body, headers={"Content-Type": "application/ipp"})
            resp = conn.getresponse()
            payload = resp.read(8 * 1024 * 1024)
            if resp.status != 200:
                raise IppError(f"HTTP {resp.status} from IPP server")
        except (OSError, http.client.HTTPException) as exc:
            raise IppError(f"Cannot reach CUPS at {self.endpoint}: {exc}") from exc
        finally:
            conn.close()
        return decode_response(payload)

    def get_printer_attributes(self, queue: str, requested: list[str] | None = None) -> IppResponse:
        attrs = [
            (TAG_URI, "printer-uri", [self.printer_uri(queue)]),
            (TAG_NAME, "requesting-user-name", [self.user]),
            (TAG_KEYWORD, "requested-attributes", requested or ["all"]),
        ]
        return self.request(f"/printers/{quote(queue, safe='')}", GET_PRINTER_ATTRIBUTES, attrs)

    def get_printers(self, requested: list[str]) -> IppResponse:
        attrs = [
            (TAG_NAME, "requesting-user-name", [self.user]),
            (TAG_KEYWORD, "requested-attributes", requested),
        ]
        return self.request("/", CUPS_GET_PRINTERS, attrs)

    def get_job_attributes(self, job_id: int, requested: list[str] | None = None) -> IppResponse:
        attrs = [
            (TAG_URI, "job-uri", [f"ipp://{self.host}:{self.port}/jobs/{int(job_id)}"]),
            (TAG_NAME, "requesting-user-name", [self.user]),
            (TAG_KEYWORD, "requested-attributes", requested or ["all"]),
        ]
        return self.request("/jobs", GET_JOB_ATTRIBUTES, attrs)
