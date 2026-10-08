import base64
import gzip
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from notaxml.certificado import Certificado

CNPJ = "12345678000199"
CHAVE = "35261099999999000199550010000012341000012345"


@pytest.fixture(scope="session")
def arquivo_pfx(tmp_path_factory):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{CNPJ}")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    dados = pkcs12.serialize_key_and_certificates(
        b"teste", chave, cert, None, serialization.BestAvailableEncryption(b"1234")
    )
    caminho = tmp_path_factory.mktemp("cert") / "teste.pfx"
    caminho.write_bytes(dados)
    return caminho


@pytest.fixture
def certificado(arquivo_pfx):
    return Certificado.carregar(arquivo_pfx, "1234")


def doc_zip(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode())).decode()


def res_nfe(chave=CHAVE, valor="1500.00", situacao="1"):
    return f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
<chNFe>{chave}</chNFe><CNPJ>99999999000199</CNPJ><xNome>FORNECEDOR SA</xNome><IE>123</IE>
<dhEmi>2026-10-01T10:00:00-03:00</dhEmi><tpNF>1</tpNF><vNF>{valor}</vNF><digVal>abc=</digVal>
<dhRecbto>2026-10-01T10:00:05-03:00</dhRecbto><nProt>135260000000001</nProt><cSitNFe>{situacao}</cSitNFe></resNFe>"""


def proc_nfe(chave=CHAVE):
    return f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><tpNF>1</tpNF><dhEmi>2026-10-01T10:00:00-03:00</dhEmi></ide>
<emit><CNPJ>99999999000199</CNPJ><xNome>FORNECEDOR SA</xNome></emit>
<total><ICMSTot><vNF>1500.00</vNF></ICMSTot></total></infNFe></NFe>
<protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><nProt>135260000000001</nProt><cStat>100</cStat></infProt></protNFe></nfeProc>"""


def proc_evento_cancelamento(chave=CHAVE):
    return f"""<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00"><evento versao="1.00">
<infEvento Id="ID110111{chave}01"><chNFe>{chave}</chNFe><tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>
<detEvento versao="1.00"><descEvento>Cancelamento</descEvento></detEvento></infEvento></evento>
<retEvento versao="1.00"><infEvento><cStat>135</cStat></infEvento></retEvento></procEventoNFe>"""


def ret_dist(cstat, ult, maxi, docs=()):
    lote = ""
    if docs:
        itens = "".join(f'<docZip NSU="{nsu}" schema="{schema}">{doc_zip(xml)}</docZip>' for nsu, schema, xml in docs)
        lote = f"<loteDistDFeInt>{itens}</loteDistDFeInt>"
    return f"""<retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>1</tpAmb>
<verAplic>1</verAplic><cStat>{cstat}</cStat><xMotivo>motivo</xMotivo><dhResp>2026-10-08T10:00:00-03:00</dhResp>
<ultNSU>{ult}</ultNSU><maxNSU>{maxi}</maxNSU>{lote}</retDistDFeInt>"""
