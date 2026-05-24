import secrets
import time


def uuid7() -> str:
    """RFC 9562 UUIDv7. 36 字符, 字典序=时序序."""
    # 48-bit timestamp (milliseconds since epoch)
    ms = int(time.time() * 1000)

    # 12-bit rand_a
    rand_a = secrets.randbits(12)

    # 62-bit rand_b
    rand_b = secrets.randbits(62)

    # Construct bytes
    # 0..47: timestamp
    # 48..51: ver (0x7)
    # 52..63: rand_a
    # 64..65: var (0x2)
    # 66..127: rand_b

    b = bytearray(16)
    # Timestamp (48 bits)
    b[0] = (ms >> 40) & 0xFF
    b[1] = (ms >> 32) & 0xFF
    b[2] = (ms >> 24) & 0xFF
    b[3] = (ms >> 16) & 0xFF
    b[4] = (ms >> 8) & 0xFF
    b[5] = ms & 0xFF

    # Version (7) and rand_a (12 bits)
    b[6] = 0x70 | ((rand_a >> 8) & 0x0F)
    b[7] = rand_a & 0xFF

    # Variant (10) and rand_b (62 bits)
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)
    b[9] = (rand_b >> 48) & 0xFF
    b[10] = (rand_b >> 40) & 0xFF
    b[11] = (rand_b >> 32) & 0xFF
    b[12] = (rand_b >> 24) & 0xFF
    b[13] = (rand_b >> 16) & 0xFF
    b[14] = (rand_b >> 8) & 0xFF
    b[15] = rand_b & 0xFF

    # Format as string: 8-4-4-4-12
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
