import base64
import io

import pyotp
import qrcode
from qrcode.image.pil import PilImage


def totp_secret_generate() -> str:
    """Generate a base32 TOTP secret.

    Returns:
        A base32 encoded random secret.
    """
    return pyotp.random_base32()


def totp_qr_url(*, secret: str, account_name: str, issuer: str) -> str:
    """Generate a TOTP QR code as a base64 data URL.

    Args:
        secret: The TOTP secret.
        account_name: The name of the account.
        issuer: The name of the issuer.

    Returns:
        A base64 encoded PNG data URL of the QR code.
    """
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


def totp_verify(*, secret: str, code: str, valid_window: int = 1) -> bool:
    """Verify a TOTP code.

    Args:
        secret: The TOTP secret.
        code: The TOTP code to verify.
        valid_window: The number of previous and next intervals to check.

    Returns:
        True if the code is valid, False otherwise.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=valid_window)
