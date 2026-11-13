"""確認済みCP932・短いUTF-16 CStringだけを書き出す。"""
import struct


def cstring(text, encoding="utf-16le"):
    if encoding == "cp932":
        raw = text.encode("cp932")
        if len(raw) < 255:
            return bytes([len(raw)]) + raw
        if len(raw) < 65535:
            return b"\xff" + struct.pack("<H", len(raw)) + raw
        raise ValueError("CP932 string exceeds supported length")
    if encoding != "utf-16le":
        raise ValueError("Unsupported CString encoding")
    raw = text.encode('utf-16le')
    size = len(raw)//2
    if size >= 255:
        raise ValueError('Prototype supports short metadata strings only')
    return b'\xff\xfe\xff' + bytes([size]) + raw
