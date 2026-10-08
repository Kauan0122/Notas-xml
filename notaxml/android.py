"""Ponto de entrada do aplicativo Android (Chaquopy): roda o NotaXML dentro do próprio celular.

O servidor escuta só em 127.0.0.1 e o aplicativo mostra a tela numa WebView. Como outros aplicativos do celular também
alcançam 127.0.0.1, o acesso exige um segredo aleatório (senha de acesso e cookie), conhecido só por este aplicativo.
"""

import os
import sys
from pathlib import Path

PREFIXO_LOG = "NOTAXML-AUTOTESTE"


def autoteste() -> bool:
    """Confere se as bibliotecas nativas e o PDF funcionam neste celular. O resultado vai para o logcat."""
    erros = []
    for modulo in ("lxml.etree", "cryptography.x509", "requests", "flask", "waitress", "sqlite3", "ssl",
                   "brazilfiscalreport.danfe"):
        try:
            __import__(modulo)
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{modulo}: {type(exc).__name__}: {exc}")
    if erros:
        for erro in erros:
            print(f"{PREFIXO_LOG}: FALHA {erro}", flush=True)
        return False
    print(f"{PREFIXO_LOG}: ok (python {sys.version.split()[0]})", flush=True)
    return True


def rodar(pasta: str, porta: int, segredo: str) -> None:
    """Sobe o servidor e só volta quando ele termina. Chamado pelo serviço Android numa thread própria."""
    os.environ["NOTAXML_WEB_SENHA"] = segredo
    os.environ["NOTAXML_ACESSO_LOCAL"] = segredo
    autoteste()

    from .web.servidor import Aplicacao, rodar as servir

    base = Path(pasta)
    base.mkdir(parents=True, exist_ok=True)
    aplicacao = Aplicacao(base / "config.toml", pasta_dados_padrao=base / "dados")
    servir(aplicacao, "127.0.0.1", porta, abrir_navegador=False)
