"""
二重螺旋 (Duet Night Abyss) DNA API Signing Module

Implements the signature algorithm used by the DNA API (dnabbs-api.yingxiong.com)
Based on reverse-engineered JS code from the official dna-api npm package.

Signing flow (H5/web mode):
  1. Generate random rk (16 chars) and sa (30 chars timestamp-mixed)
  2. Build payload with token + sa, then serialize sorted
  3. MD5 -> shuffle_md5 -> xor_encode(rk) -> concat with RSA_encrypt(rk)
  4. Return {rk, tn, sa} for headers
"""

import base64
import hashlib
import logging
import random
import string
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_der_public_key, load_pem_public_key

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────────


def rand_str(length: int = 16) -> str:
    """y() in JS: random alphanumeric (a-zA-Z0-9) string"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def rand_str2(length: int = 16) -> str:
    """R() in JS: random lowercase alphanumeric (a-z0-9) string"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


def md5_upper(text: str) -> str:
    """k() in JS: MD5 hex digest in UPPERCASE"""
    return hashlib.md5(text.encode('utf-8')).hexdigest().upper()


def shuffle_md5(md5_hex: str) -> str:
    """ne() in JS: swap char positions: 1↔13, 5↔17, 7↔23"""
    if len(md5_hex) <= 23:
        return md5_hex
    chars = list(md5_hex)
    swaps = [(1, 13), (5, 17), (7, 23)]
    for a, b in swaps:
        chars[a], chars[b] = chars[b], chars[a]
    return ''.join(chars)


def swap_positions(s: str, swaps: list) -> str:
    """x() in JS: swap characters at given positions"""
    chars = list(s)
    for a, b in swaps:
        if 0 <= a < len(chars) and 0 <= b < len(chars):
            chars[a], chars[b] = chars[b], chars[a]
    return ''.join(chars)


def rsa_encrypt(text: str, public_key_b64: str) -> str:
    """
    I() in JS: RSA PKCS1v15 encryption with node-forge.
    Encrypts in chunks of 117 bytes, then base64 encodes.
    """
    try:
        # Build PEM public key
        key_bytes = []
        for i in range(0, len(public_key_b64), 64):
            key_bytes.append(public_key_b64[i:i + 64])
        pem = '-----BEGIN PUBLIC KEY-----\n' + '\n'.join(key_bytes) + '\n-----END PUBLIC KEY-----'

        # Load public key
        public_key = load_pem_public_key(pem.encode('ascii'))

        # Encrypt in chunks of 117 bytes (max for PKCS1v15 with 1024-bit key)
        # Note: the real key might be 2048-bit, adjust chunk size if needed
        chunk_size = 117
        data = text.encode('utf-8')
        result = b''
        key_size = public_key.key_size // 8  # in bytes
        max_chunk = key_size - 11  # PKCS1v15 overhead

        for i in range(0, len(data), max_chunk):
            chunk = data[i:i + max_chunk]
            result += public_key.encrypt(
                chunk,
                padding.PKCS1v15()
            )

        return base64.b64encode(result).decode('ascii')
    except Exception as e:
        raise ValueError(f"RSA encryption failed: {e}")


# ─── SA generation ──────────────────────────────────────────────────────────


def generate_sa_h5() -> tuple:
    """
    Ce() + Le() in JS:
    Generate a 30-char SA string with timestamp mixed in, then shuffle.
    returns (raw_sa, shuffled_sa)
    """
    # Ce(): build 30-char string from timestamp + random chars
    # Positions 8-12: timestamp[0-4], 16-20: timestamp[5-9], 22-24: timestamp[10-12]
    # Rest: random alphanumeric chars
    ts = str(int(time.time() * 1000))  # millisecond timestamp
    rand_part = rand_str(30)

    raw = [''] * 30
    ti = 0
    ri = 0
    for pos in range(30):
        if 8 <= pos <= 12:
            raw[pos] = ts[ti] if ti < len(ts) else '0'
            ti += 1
        elif 16 <= pos <= 20:
            raw[pos] = ts[ti] if ti < len(ts) else '0'
            ti += 1
        elif 22 <= pos <= 24:
            raw[pos] = ts[ti] if ti < len(ts) else '0'
            ti += 1
        else:
            raw[pos] = rand_part[ri]
            ri += 1

    raw_sa = ''.join(raw)

    # Le(): shuffle: swap 2↔23, 9↔17, 13↔25
    shuffled = swap_positions(raw_sa, [(2, 23), (9, 17), (13, 25)])

    return raw_sa, shuffled


def build_sign_string(params: dict, key: str) -> str:
    """
    Ae() in JS: sort keys, build 'k=v&k=v' + key (no separator).
    Uses null/undefined/empty check like JS Ae() — more strict than truthy check.
    """
    sorted_keys = sorted(params.keys())
    pairs = []
    for k in sorted_keys:
        v = params[k]
        if v is not None and v != '':  # null/undefined/empty check like Ae()
            pairs.append(f"{k}={v}")
    return '&'.join(pairs) + key


def build_sign_string_v2(params: dict, key: str) -> str:
    """
    de() in JS: sort keys, build 'k=v&k=v' + key (no separator).
    Uses truthy check (if s is truthy), not null check like Ae().
    """
    sorted_keys = sorted(params.keys())
    pairs = []
    for k in sorted_keys:
        v = params[k]
        if v:  # truthy check like JS
            pairs.append(f"{k}={v}")
    return '&'.join(pairs) + key


def xor_encode(text: str, key: str) -> str:
    """
    T() in JS: xor-like encoding by adding byte values, wrapping with '@'.
    For each byte in text, add corresponding byte from key (cycling),
    return as '@value' concatenated.
    """
    text_bytes = text.encode('utf-8')
    key_bytes = key.encode('utf-8')
    result = []
    for i, tb in enumerate(text_bytes):
        val = (tb & 0xFF) + (key_bytes[i % len(key_bytes)] & 0xFF)
        result.append(f"@{val}")
    return ''.join(result)


def build_signature_h5(public_key_b64: str, payload: dict, token: str = None) -> dict:
    """
    te() in JS: build H5-mode request signature.

    Args:
        public_key_b64: RSA public key (base64)
        payload: request body parameters
        token: auth token

    Returns:
        {rk, tn, sa} where:
        - rk: random key (16 chars)
        - tn: encrypted signature value
        - sa: shuffled SA string (set as header)
    """
    rk = rand_str(16)
    raw_sa, shuffled_sa = generate_sa_h5()

    # Build augmented payload
    augmented = {}
    for k, v in payload.items():
        augmented[k] = str(v)
    if token:
        augmented['token'] = token
    augmented['sa'] = raw_sa  # use raw (un-shuffled) SA in payload

    # o = md5_upper(de(augmented, rk))
    sign_str = build_sign_string_v2(augmented, rk)
    o = md5_upper(sign_str)

    # u = T(ne(o), rk)  = xor_encode(shuffle_md5(o), rk)
    u = xor_encode(shuffle_md5(o), rk)

    # tn = rsa_encrypt(rk, pubKey) + ',' + u
    encrypted_rk = rsa_encrypt(rk, public_key_b64)
    tn = f"{encrypted_rk},{u}"

    return {'rk': rk, 'tn': tn, 'sa': shuffled_sa}


def build_signature_130(public_key_b64: str, payload: dict, token: str = None) -> dict:
    """
    re() in JS: build Android app v1.3.0 request signature.
    Uses De(30) for SA (numeric random) + fe() processing.
    Uses Z() (sign_shuffled) instead of k(de()).
    """
    rk = rand_str(16)
    # De(30): 30-char numeric random (using Java Random seed simulation)
    raw_sa = rand_str2(30)  # simplified: using alphanumeric instead of pure numeric
    # fe(): process SA with timestamp insertion + swaps
    processed_sa = process_sa_130(raw_sa)

    augmented = {}
    for k, v in payload.items():
        augmented[k] = str(v)
    if token:
        augmented['token'] = token
    augmented['sa'] = raw_sa

    # Z(a, rk) = shuffle_md5(md5_upper(build_sign_string(augmented, rk)))
    sign_str = build_sign_string(augmented, rk)
    o = shuffle_md5(md5_upper(sign_str))

    u = xor_encode(o, rk)
    encrypted_rk = rsa_encrypt(rk, public_key_b64)
    tn = f"{encrypted_rk},{u}"

    return {'rk': rk, 'tn': tn, 'sa': processed_sa}


def process_sa_130(raw_sa: str) -> str:
    """
    fe() in JS: SA processing for v1.3.0 signature.
    Performs position swaps and timestamp insertion.
    """
    # Swap positions
    s = swap_positions(raw_sa, [(1, 17), (9, 20), (15, 16), (22, 27)])
    ts = str(int(time.time() * 1000))

    if len(s) != 30 or len(ts) < 13:
        return s

    result = []
    ti = 0
    for pos in range(len(s)):
        if pos == 8 or pos == 16:
            result.append(ts[ti:ti + 5])
            ti += 5
        elif pos == 22:
            result.append(ts[ti:ti + 3])
            ti += 3
        result.append(s[pos])
    return ''.join(result)


# ─── Header generation ──────────────────────────────────────────────────────


def get_h5_base_headers(token: str = None) -> dict:
    """Get base headers for H5 (web/browser) mode API requests."""
    headers = {
        'version': '3.11.1',
        'source': 'h5',
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    }
    if token:
        headers['token'] = token
    headers['origin'] = 'https://dnabbs.yingxiong.com'
    headers['refer'] = 'https://dnabbs.yingxiong.com/'
    return headers


# Session-level device code (generated once like JS constructor does)
_DEVICE_CODE: str | None = None


def _get_device_code() -> str:
    """Generate or return cached device code like JS generateDeviceCode()."""
    global _DEVICE_CODE
    if _DEVICE_CODE is None:
        _DEVICE_CODE = '2' + rand_str2(32)
    return _DEVICE_CODE


def build_signed_request(public_key_b64: str, payload: dict, token: str) -> tuple:
    """
    Build a fully signed request using v1.3.0 (Android native) signature mode.
    Matches the JS _dna_request -> getHeaders -> re() flow.

    Returns:
        (headers_dict, urlencoded_payload)
    """
    sig = build_signature_130(public_key_b64, payload, token)
    headers = {
        'countrycode': 'CN',
        'version': '1.3.0',
        'versioncode': '10',
        'source': 'android',
        'lang': 'zh-Hans',
        'devCode': _get_device_code(),
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'okhttp/3.10.0',
        'token': token,
        'tn': sig['tn'],
        'sa': sig['sa'],
    }

    import urllib.parse
    body = urllib.parse.urlencode(payload)

    return headers, body


def build_unsigned_request(token: str = None) -> dict:
    """Build headers for requests that DON'T need signing (e.g., isHaveSignin)."""
    return get_h5_base_headers(token)
