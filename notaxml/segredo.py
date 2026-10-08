"""Guarda a senha do certificado criptografada pelo Windows (DPAPI), vinculada ao usuário logado.

Fora do Windows não há cofre equivalente sem dependências extras; nesse caso a senha não é lembrada.
"""

import base64
import sys

PREFIXO = "dpapi:"


def disponivel() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01
    _ENTROPIA = b"notaxml-certificado"

    def _blob(dados: bytes) -> _Blob:
        buffer = ctypes.create_string_buffer(dados, len(dados))
        return _Blob(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))

    def _chamar(funcao, dados: bytes) -> bytes:
        entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _Blob()
        if not funcao(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
                      _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida)):
            raise OSError(ctypes.get_last_error(), "Falha ao usar o cofre do Windows (DPAPI).")
        try:
            return ctypes.string_at(saida.pbData, saida.cbData)
        finally:
            _kernel32.LocalFree(saida.pbData)


def proteger(texto: str) -> str:
    if not disponivel():
        raise RuntimeError("Guardar a senha só é possível no Windows.")
    return PREFIXO + base64.b64encode(_chamar(_crypt32.CryptProtectData, texto.encode())).decode()


def revelar(valor: str) -> str:
    """Devolve o texto original. Valores sem o prefixo 'dpapi:' são devolvidos como estão."""
    if not valor.startswith(PREFIXO):
        return valor
    if not disponivel():
        raise RuntimeError("Esta senha foi guardada pelo Windows e só pode ser lida nele.")
    return _chamar(_crypt32.CryptUnprotectData, base64.b64decode(valor[len(PREFIXO):])).decode()
