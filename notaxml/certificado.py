import base64
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from .erros import ErroCertificado


class Certificado:
    """Certificado digital A1 (arquivo .pfx/.p12) da empresa."""

    def __init__(self, chave, certificado: x509.Certificate, adicionais: list[x509.Certificate]):
        if not isinstance(chave, rsa.RSAPrivateKey):
            raise ErroCertificado("O certificado precisa ter uma chave privada RSA (padrão ICP-Brasil).")
        self.chave = chave
        self.certificado = certificado
        self.adicionais = adicionais

    @classmethod
    def carregar(cls, caminho: str | Path, senha: str) -> "Certificado":
        caminho = Path(caminho)
        if not caminho.is_file():
            raise ErroCertificado(f"Arquivo de certificado não encontrado: {caminho}")
        try:
            chave, cert, adicionais = pkcs12.load_key_and_certificates(caminho.read_bytes(), senha.encode())
        except ValueError as exc:
            raise ErroCertificado("Não foi possível abrir o certificado: senha incorreta ou arquivo inválido.") from exc
        if chave is None or cert is None:
            raise ErroCertificado("O arquivo não contém certificado e chave privada (use um certificado A1).")
        return cls(chave, cert, list(adicionais or []))

    @property
    def titular(self) -> str:
        nomes = self.certificado.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return str(nomes[0].value) if nomes else self.certificado.subject.rfc4514_string()

    @property
    def cnpj(self) -> str | None:
        # e-CNPJ ICP-Brasil: CN = "RAZAO SOCIAL:12345678000199"
        achado = re.search(r":(\d{14})\b", self.titular)
        return achado.group(1) if achado else None

    @property
    def valido_ate(self) -> datetime:
        return self.certificado.not_valid_after_utc

    @property
    def vencido(self) -> bool:
        return self.valido_ate < datetime.now(timezone.utc)

    def der_base64(self) -> str:
        return base64.b64encode(self.certificado.public_bytes(serialization.Encoding.DER)).decode()

    def assinar_rsa_sha1(self, dados: bytes) -> bytes:
        # O leiaute da NF-e exige RSA-SHA1 nas assinaturas XML.
        return self.chave.sign(dados, padding.PKCS1v15(), hashes.SHA1())

    @contextmanager
    def arquivos_pem(self):
        """Grava certificado e chave em arquivos temporários (somente leitura do dono) para o TLS mútuo.

        Os arquivos são apagados ao sair do bloco.
        """
        pasta = tempfile.mkdtemp(prefix="notaxml-")
        try:
            caminho_cert = os.path.join(pasta, "cert.pem")
            caminho_chave = os.path.join(pasta, "chave.pem")
            cadeia = b"".join(
                c.public_bytes(serialization.Encoding.PEM) for c in [self.certificado, *self.adicionais]
            )
            chave = self.chave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            for caminho, conteudo in ((caminho_cert, cadeia), (caminho_chave, chave)):
                fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as arquivo:
                    arquivo.write(conteudo)
            yield caminho_cert, caminho_chave
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
