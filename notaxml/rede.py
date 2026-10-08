import socket

TAMANHO_MINIMO_SENHA = 8
ENDERECOS_LOCAIS = ("127.0.0.1", "localhost", "::1")


def endereco_na_rede() -> str | None:
    """Endereço desta máquina na rede local (não envia nenhum pacote)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            endereco = s.getsockname()[0]
        except OSError:
            return None
    return None if endereco.startswith("127.") else endereco
