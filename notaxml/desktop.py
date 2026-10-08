"""Ponto de entrada do NotaXML.exe: dois cliques e o sistema abre no navegador."""

import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path

from .config import ler_secoes

PORTA_PADRAO = 8000


def _pasta_programa() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def pastas() -> tuple[Path, Path]:
    """(pasta da configuração e do certificado, pasta padrão dos XMLs).

    Modo portátil: se existir config.toml ao lado do .exe, tudo fica ali.
    Senão a configuração fica em %LOCALAPPDATA%\\NotaXML (fora do OneDrive) e os XMLs em Documentos\\NotaXML.
    """
    portatil = _pasta_programa()
    if (portatil / "config.toml").is_file():
        return portatil, portatil / "dados"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "NotaXML"
        documentos = Path.home() / "Documents"
        return base, (documentos if documentos.is_dir() else Path.home()) / "NotaXML"
    return Path.home() / ".notaxml", Path.home() / "NotaXML"


def _ja_rodando(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/saude", timeout=2) as resposta:
            return resposta.read() == b"notaxml"
    except OSError:
        return False


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def _escolher_porta(preferida: int) -> int | None:
    for porta in range(preferida, preferida + 20):
        if _ja_rodando(porta):
            return -porta  # negativo: já existe um NotaXML aberto nessa porta
        if _porta_livre(porta):
            return porta
    return None


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # mensagens aparecem na hora, mesmo redirecionadas
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("NotaXML")

    pasta_config, pasta_dados = pastas()
    pasta_config.mkdir(parents=True, exist_ok=True)
    caminho_config = pasta_config / "config.toml"
    preferida = int(ler_secoes(caminho_config).get("web", {}).get("porta", PORTA_PADRAO))

    porta = _escolher_porta(preferida)
    if porta is None:
        print(f"Nenhuma porta livre entre {preferida} e {preferida + 19}.")
        return 1
    if porta < 0:
        print("O NotaXML já está aberto; abrindo o navegador.")
        webbrowser.open(f"http://127.0.0.1:{-porta}")
        return 0

    from .web.servidor import Aplicacao, rodar

    print("=" * 60)
    print(" NotaXML - download de notas fiscais da SEFAZ")
    print(" Mantenha esta janela aberta enquanto usa o sistema.")
    print(" Para encerrar, feche esta janela.")
    print("=" * 60)
    print(f"Configuração: {caminho_config}")
    print(f"XMLs:         {pasta_dados}")
    rodar(Aplicacao(caminho_config, pasta_dados_padrao=pasta_dados, desktop=True), "127.0.0.1", porta,
          abrir_navegador=not os.environ.get("NOTAXML_SEM_NAVEGADOR"))
    return 0


def iniciar():
    try:
        codigo = main()
    except KeyboardInterrupt:
        codigo = 0
    except Exception:  # noqa: BLE001 - janela não pode sumir sem mostrar o erro
        import traceback
        traceback.print_exc()
        codigo = 1
    if codigo and getattr(sys, "frozen", False):
        input("\nPressione Enter para fechar...")
    raise SystemExit(codigo)


if __name__ == "__main__":
    iniciar()
