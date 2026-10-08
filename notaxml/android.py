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
    if not erros:
        erros += _autoteste_funcional()
    if erros:
        for erro in erros:
            print(f"{PREFIXO_LOG}: FALHA {erro}", flush=True)
        return False
    print(f"{PREFIXO_LOG}: ok (python {sys.version.split()[0]})", flush=True)
    return True


def _autoteste_funcional() -> list[str]:
    """Usa de verdade o que o sistema precisa no dia a dia: assinar um evento da SEFAZ e desenhar um PDF."""
    erros = []
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12

        from .certificado import Certificado
        from .manifestacao import montar_evento
        from .xmlutil import NS, parse, serializar

        chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "AUTOTESTE:11222333000181")])
        agora = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(agora - datetime.timedelta(days=1))
                .not_valid_after(agora + datetime.timedelta(days=1)).sign(chave, hashes.SHA256()))
        pfx = pkcs12.serialize_key_and_certificates(b"t", chave, cert, None,
                                                    serialization.BestAvailableEncryption(b"1234"))
        certificado = Certificado.de_bytes(pfx, "1234")  # abre o .pfx como no uso real
        with certificado.arquivos_pem() as (arquivo_cert, arquivo_chave):  # PEMs temporários do TLS mútuo
            if not (os.path.getsize(arquivo_cert) and os.path.getsize(arquivo_chave)):
                erros.append("pem: arquivos temporários vazios")
        evento = montar_evento(certificado, 2, "11222333000181", "3" * 44, "ciencia")  # RSA-SHA1 + C14N (lxml)
        if parse(serializar(evento)).find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue") is None:
            erros.append("assinatura: evento sem SignatureValue")
        if NS["n"] not in serializar(evento).decode():
            erros.append("assinatura: namespace da NF-e ausente")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"assinatura: {type(exc).__name__}: {exc}")
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(0, 10, "NotaXML - autoteste de PDF")
        if not bytes(pdf.output()).startswith(b"%PDF"):
            erros.append("pdf: saída inválida")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"pdf: {type(exc).__name__}: {exc}")
    try:
        from .amostra_nfe import nfe_completa
        from .danfe import gerar_danfe

        danfe = gerar_danfe(nfe_completa().encode())  # DANFE completo: código de barras, fontes, tabelas
        if not danfe.startswith(b"%PDF") or len(danfe) < 3000:
            erros.append(f"danfe: PDF suspeito ({len(danfe)} bytes)")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"danfe: {type(exc).__name__}: {exc}")
    return erros


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
