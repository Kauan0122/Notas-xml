"""Monta uma pasta portátil de teste para o NotaXML.exe: configuração, certificado falso e uma NF-e de exemplo.

Uso: python empacotamento/preparar_teste.py PASTA
Depois copie o executável para PASTA e abra-o (senha do certificado: variável NFE_CERT_SENHA=1234).
Imprime a chave da nota de exemplo.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from notaxml.armazenamento import Armazenamento  # noqa: E402
from notaxml.config import salvar_config  # noqa: E402
from tests.nfe_exemplo import CHAVE_COMPLETA, nfe_completa  # noqa: E402

CNPJ = "11222333000181"


def preparar(pasta: Path) -> str:
    pasta.mkdir(parents=True, exist_ok=True)
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{CNPJ}")])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
            .not_valid_after(agora + timedelta(days=30)).sign(chave, hashes.SHA256()))
    (pasta / "certificado.pfx").write_bytes(pkcs12.serialize_key_and_certificates(
        b"t", chave, cert, None, serialization.BestAvailableEncryption(b"1234")))
    salvar_config(pasta / "config.toml", {
        "empresa": {"cnpj": CNPJ, "uf": "SP"},
        "certificado": {"arquivo": "certificado.pfx"},
        "sefaz": {"ambiente": "homologacao"},
        "armazenamento": {"pasta": "dados"},
        "web": {"sincronizacao_automatica": False},
    })
    banco = Armazenamento(pasta / "dados")
    banco.guardar("procNFe", nfe_completa().encode())
    banco.fechar()
    return CHAVE_COMPLETA


if __name__ == "__main__":
    print(preparar(Path(sys.argv[1])))
