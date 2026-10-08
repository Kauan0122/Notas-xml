"""Ponto de entrada do NotaXML.exe: dois cliques e o sistema abre no navegador.

Com --servidor ele fica aberto para a rede interna (sem abrir o navegador), protegido por senha de acesso.
"""

import argparse
import getpass
import os
import socket
import sys
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

from . import segredo
from .config import ler_config_web, ler_secoes, salvar_config
from .erros import ErroNotaXML

PORTA_PADRAO = 8000
TAMANHO_MINIMO_SENHA = 8


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


def _porta_livre(porta: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, porta))
            return True
        except OSError:
            return False


def _escolher_porta(preferida: int, host: str = "127.0.0.1") -> int | None:
    for porta in range(preferida, preferida + 20):
        if _ja_rodando(porta):
            return -porta  # negativo: já existe um NotaXML aberto nessa porta
        if _porta_livre(porta, host):
            return porta
    return None


def _endereco_na_rede() -> str | None:
    """Endereço desta máquina na rede local (não envia nenhum pacote)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            endereco = s.getsockname()[0]
        except OSError:
            return None
    return None if endereco.startswith("127.") else endereco


def _pedir_senha() -> str:
    if not sys.stdin or not sys.stdin.isatty():
        raise ErroNotaXML(
            "Ainda não há senha de acesso definida. Abra o NotaXML.exe --servidor uma vez numa janela do "
            "Prompt de Comando para definir a senha (depois ele pode rodar sem ninguém conectado)."
        )
    print("\nDefina a senha de acesso ao sistema (será pedida nos outros computadores da rede).")
    while True:
        senha = getpass.getpass("Nova senha de acesso: ")
        if len(senha) < TAMANHO_MINIMO_SENHA:
            print(f"Use pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
        elif senha != getpass.getpass("Repita a senha: "):
            print("As senhas não conferem.")
        else:
            return senha


def configurar_servidor(caminho_config: Path, pedir_senha: Callable[[], str] = _pedir_senha) -> None:
    """Garante senha de acesso e acesso pela rede no config.toml (sem mexer no resto da configuração)."""
    web = ler_config_web(caminho_config)
    secoes = ler_secoes(caminho_config)
    secao = secoes.setdefault("web", {})
    if not web.senha:
        senha = pedir_senha()
        # no Windows a senha fica criptografada pelo cofre do sistema, ligada ao usuário
        secao["senha"] = segredo.proteger(senha) if segredo.disponivel() else senha
        print("Senha de acesso salva.")
    if web.host in ("127.0.0.1", "localhost", "::1"):
        secao["host"] = "0.0.0.0"
    salvar_config(caminho_config, secoes)


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="NotaXML", description="NotaXML - download de NF-e da SEFAZ.")
    parser.add_argument("--servidor", action="store_true",
                        help="abre o sistema para a rede interna, com senha de acesso (não abre o navegador)")
    parser.add_argument("--redefinir-senha", action="store_true",
                        help="com --servidor: pede uma nova senha de acesso")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)
    sys.stdout.reconfigure(line_buffering=True)  # mensagens aparecem na hora, mesmo redirecionadas
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("NotaXML (servidor)" if args.servidor else "NotaXML")

    pasta_config, pasta_dados = pastas()
    pasta_config.mkdir(parents=True, exist_ok=True)
    caminho_config = pasta_config / "config.toml"

    if args.servidor:
        if args.redefinir_senha:
            secoes = ler_secoes(caminho_config)
            secoes.get("web", {}).pop("senha", None)
            if secoes:
                salvar_config(caminho_config, secoes)
        configurar_servidor(caminho_config)

    web = ler_config_web(caminho_config)
    host = web.host
    preferida = int(ler_secoes(caminho_config).get("web", {}).get("porta", PORTA_PADRAO))

    porta = _escolher_porta(preferida, host)
    if porta is None:
        print(f"Nenhuma porta livre entre {preferida} e {preferida + 19}.")
        return 1
    if porta < 0:
        print("O NotaXML já está aberto.")
        if not args.servidor:
            webbrowser.open(f"http://127.0.0.1:{-porta}")
        return 0

    from .web.servidor import Aplicacao, host_local, rodar

    if not host_local(host) and not web.senha:
        raise ErroNotaXML("Para abrir o sistema na rede é preciso uma senha de acesso. Use NotaXML.exe --servidor.")

    print("=" * 60)
    print(" NotaXML - download de notas fiscais da SEFAZ")
    print(" Mantenha esta janela aberta enquanto usa o sistema.")
    print(" Para encerrar, feche esta janela.")
    print("=" * 60)
    print(f"Configuração: {caminho_config}")
    print(f"XMLs:         {pasta_dados}")
    if not host_local(host):
        rede = _endereco_na_rede()
        print(f"Nos outros computadores da rede, abra: http://{rede or 'IP-DESTE-COMPUTADOR'}:{porta}")
    rodar(Aplicacao(caminho_config, pasta_dados_padrao=pasta_dados, desktop=host_local(host)), host, porta,
          abrir_navegador=not args.servidor and not os.environ.get("NOTAXML_SEM_NAVEGADOR"))
    return 0


def iniciar():
    try:
        codigo = main()
    except KeyboardInterrupt:
        codigo = 0
    except ErroNotaXML as exc:
        print(f"Erro: {exc}")
        codigo = 1
    except Exception:  # noqa: BLE001 - janela não pode sumir sem mostrar o erro
        import traceback
        traceback.print_exc()
        codigo = 1
    if codigo and getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        input("\nPressione Enter para fechar...")
    raise SystemExit(codigo)


if __name__ == "__main__":
    iniciar()
