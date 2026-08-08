import secrets
import string

# No 0/O/1/I/L — these get misread when a customer reads a code to support.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_public_code(length: int = 8) -> str:
    """Human-readable booking reference, e.g. 'VLT7QK2M4X'.

    Random rather than sequential: a sequential public id lets anyone count
    daily order volume and probe other customers' bookings by incrementing.
    """
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"VLT{body}"
