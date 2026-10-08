"""Web service NFeDistribuicaoDFe (Ambiente Nacional)."""

import base64
import gzip
from dataclasses import dataclass, field

from lxml import etree

from .erros import ErroSefaz
from .soap import ClienteSefaz
from .xmlutil import NS, el, sub, texto

URLS = {
    1: "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    2: "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
ACAO = f"{NS_WSDL}/nfeDistDFeInteresse"

CSTAT_NENHUM_DOCUMENTO = "137"
CSTAT_DOCUMENTOS_LOCALIZADOS = "138"
CSTAT_CONSUMO_INDEVIDO = "656"


@dataclass
class DocumentoDistribuido:
    nsu: str
    schema: str
    xml: bytes

    @property
    def tipo(self) -> str:
        # ex.: "procNFe_v4.00.xsd" -> "procNFe"
        return self.schema.split("_")[0]


@dataclass
class RetornoDistribuicao:
    cstat: str
    motivo: str
    ult_nsu: str
    max_nsu: str
    documentos: list[DocumentoDistribuido] = field(default_factory=list)


def montar_pedido(ambiente: int, cuf: int, documento: str, *, ult_nsu: str | None = None, chave: str | None = None):
    pedido = el("distDFeInt", versao="1.01")
    sub(pedido, "tpAmb", str(ambiente))
    sub(pedido, "cUFAutor", str(cuf))
    sub(pedido, "CPF" if len(documento) == 11 else "CNPJ", documento)
    if chave is not None:
        sub(sub(pedido, "consChNFe"), "chNFe", chave)
    else:
        sub(sub(pedido, "distNSU"), "ultNSU", (ult_nsu or "0").zfill(15))
    return pedido


def interpretar_retorno(ret: etree._Element) -> RetornoDistribuicao:
    documentos = []
    for doc in ret.iterfind("n:loteDistDFeInt/n:docZip", namespaces=NS):
        xml = gzip.decompress(base64.b64decode(doc.text or ""))
        documentos.append(DocumentoDistribuido(nsu=doc.get("NSU", ""), schema=doc.get("schema", ""), xml=xml))
    return RetornoDistribuicao(
        cstat=texto(ret, "n:cStat") or "",
        motivo=texto(ret, "n:xMotivo") or "",
        ult_nsu=texto(ret, "n:ultNSU") or "",
        max_nsu=texto(ret, "n:maxNSU") or "",
        documentos=documentos,
    )


class DistribuicaoDFe:
    def __init__(self, cliente: ClienteSefaz, ambiente: int, cuf: int, documento: str):
        self.cliente = cliente
        self.ambiente = ambiente
        self.cuf = cuf
        self.documento = documento

    def _consultar(self, pedido) -> RetornoDistribuicao:
        operacao = etree.Element(f"{{{NS_WSDL}}}nfeDistDFeInteresse", nsmap={None: NS_WSDL})
        etree.SubElement(operacao, f"{{{NS_WSDL}}}nfeDadosMsg").append(pedido)
        resposta = self.cliente.chamar(URLS[self.ambiente], ACAO, operacao)
        ret = resposta.find(".//n:retDistDFeInt", namespaces=NS)
        if ret is None:
            raise ErroSefaz("Resposta da SEFAZ não contém retDistDFeInt.")
        return interpretar_retorno(ret)

    def consultar_nsu(self, ult_nsu: str) -> RetornoDistribuicao:
        return self._consultar(montar_pedido(self.ambiente, self.cuf, self.documento, ult_nsu=ult_nsu))

    def consultar_chave(self, chave: str) -> RetornoDistribuicao:
        return self._consultar(montar_pedido(self.ambiente, self.cuf, self.documento, chave=chave))

