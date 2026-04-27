def encode_varint32(value: int) -> bytes:
    if value < 0:
        raise ValueError("Varint32 only supports non-negative integers.")

    encoded = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            encoded.append(chunk | 0x80)
        else:
            encoded.append(chunk)
            return bytes(encoded)


def read_exact(sock, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Socket closed while receiving message bytes.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_varint32(sock) -> int:
    shift = 0
    result = 0
    while True:
        raw = sock.recv(1)
        if not raw:
            raise ConnectionError("Socket closed while receiving varint32 prefix.")
        byte = raw[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result
        shift += 7
        if shift >= 35:
            raise ValueError("Invalid varint32 prefix.")


def send_delimited_message(sock, message) -> None:
    payload = message.SerializeToString()
    sock.sendall(encode_varint32(len(payload)) + payload)


def read_delimited_message(sock) -> bytes:
    size = read_varint32(sock)
    return read_exact(sock, size)
