"""Manifestação do Destinatário (NFeRecepcaoEvento4 no Ambiente Nacional)."""

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta

from lxml import etree

from .assinatura import assinar
from .certificado import Certificado
from .erros import ErroSefaz
from .soap import ClienteSefaz
from .xmlutil import NS, NS_NFE, el, sub, texto

URLS = {
    1: "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    2: "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
}
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4"
ACAO = f"{NS_WSDL}/nfeRecepcaoEvento"
ORGAO_AMBIENTE_NACIONAL = "91"
MAX_EVENTOS_POR_LOTE = 20

# nome usado na linha de comando -> (código, descrição oficial)
EVENTOS = {
    "ciencia": ("210210", "Ciencia da Operacao"),
    "confirmacao": ("210200", "Confirmacao da Operacao"),
    "desconhecimento": ("210220", "Desconhecimento da Operacao"),
    "nao-realizada": ("210240", "Operacao nao Realizada"),
}
DESCRICAO_EVENTO = {codigo: nome for nome, (codigo, _) in EVENTOS.items()}

# 135 = evento registrado e vinculado; 136 = registrado sem vínculo; 573 = duplicidade (já manifestado)
CSTAT_SUCESSO = {"135", "136", "573"}


@dataclass
class ResultadoEvento:
    chave: str
    tipo: str
    cstat: str
    motivo: str
    protocolo: str | None
    xml_proc: bytes | None  # procEventoNFe pronto para arquivar (quando registrado)

    @property
    def sucesso(self) -> bool:
        return self.cstat in CSTAT_SUCESSO


def _agora() -> str:
    # Um minuto de folga evita a rejeição 578 (data do evento no futuro) por relógio adiantado.
    return (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")


def montar_evento(certificado: Certificado, ambiente: int, documento: str, chave: str, tipo: str,
                  justificativa: str | None = None, sequencia: int = 1) -> etree._Element:
    codigo, descricao = EVENTOS[tipo]
    if tipo == "nao-realizada" and not (justificativa and 15 <= len(justificativa) <= 255):
        raise ValueError("'Operação não realizada' exige justificativa entre 15 e 255 caracteres.")

    evento = el("evento", versao="1.00")
    inf = sub(evento, "infEvento", Id=f"ID{codigo}{chave}{sequencia:02d}")
    sub(inf, "cOrgao", ORGAO_AMBIENTE_NACIONAL)
    sub(inf, "tpAmb", str(ambiente))
    sub(inf, "CPF" if len(documento) == 11 else "CNPJ", documento)
    sub(inf, "chNFe", chave)
    sub(inf, "dhEvento", _agora())
    sub(inf, "tpEvento", codigo)
    sub(inf, "nSeqEvento", str(sequencia))
    sub(inf, "verEvento", "1.00")
    det = sub(inf, "detEvento", versao="1.00")
    sub(det, "descEvento", descricao)
    if tipo == "nao-realizada":
        sub(det, "xJust", justificativa)
    assinar(evento, inf, certificado)
    return evento


def montar_lote(eventos: list[etree._Element], id_lote: str) -> etree._Element:
    lote = el("envEvento", versao="1.00")
    sub(lote, "idLote", id_lote)
    for evento in eventos:
        lote.append(evento)
    return lote


def interpretar_retorno(ret: etree._Element, eventos: list[etree._Element]) -> list[ResultadoEvento]:
    cstat_lote = texto(ret, "n:cStat")
    if cstat_lote != "128":
        raise ErroSefaz(f"Lote de eventos rejeitado: {cstat_lote} - {texto(ret, 'n:xMotivo')}", cstat_lote)

    enviados = {(texto(e, "n:infEvento/n:chNFe"), texto(e, "n:infEvento/n:tpEvento")): e for e in eventos}
    resultados = []
    for ret_evento in ret.iterfind("n:retEvento", namespaces=NS):
        inf = ret_evento.find("n:infEvento", namespaces=NS)
        chave, tipo = texto(inf, "n:chNFe") or "", texto(inf, "n:tpEvento") or ""
        cstat = texto(inf, "n:cStat") or ""
        xml_proc = None
        enviado = enviados.get((chave, tipo))
        if cstat in {"135", "136"} and enviado is not None:
            proc = el("procEventoNFe", versao="1.00")
            proc.append(copy.deepcopy(enviado))
            proc.append(copy.deepcopy(ret_evento))
            xml_proc = etree.tostring(proc, encoding="utf-8", xml_declaration=True)
        resultados.append(ResultadoEvento(
            chave=chave, tipo=tipo, cstat=cstat, motivo=texto(inf, "n:xMotivo") or "",
            protocolo=texto(inf, "n:nProt"), xml_proc=xml_proc,
        ))
    return resultados


class Manifestacao:
    def __init__(self, cliente: ClienteSefaz, certificado: Certificado, ambiente: int, documento: str):
        self.cliente = cliente
        self.certificado = certificado
        self.ambiente = ambiente
        self.documento = documento

    def enviar(self, chaves: list[str], tipo: str, justificativa: str | None = None) -> list[ResultadoEvento]:
        resultados = []
        for inicio in range(0, len(chaves), MAX_EVENTOS_POR_LOTE):
            grupo = chaves[inicio:inicio + MAX_EVENTOS_POR_LOTE]
            eventos = [
                montar_evento(self.certificado, self.ambiente, self.documento, chave, tipo, justificativa)
                for chave in grupo
            ]
            id_lote = datetime.now().strftime("%y%m%d%H%M%S") + f"{inicio:03d}"
            dados = etree.Element(f"{{{NS_WSDL}}}nfeDadosMsg", nsmap={None: NS_WSDL})
            dados.append(montar_lote(eventos, id_lote))
            resposta = self.cliente.chamar(URLS[self.ambiente], ACAO, dados)
            ret = resposta if resposta.tag == f"{{{NS_NFE}}}retEnvEvento" else resposta.find(".//n:retEnvEvento", namespaces=NS)
            if ret is None:
                raise ErroSefaz("Resposta da SEFAZ não contém retEnvEvento.")
            resultados.extend(interpretar_retorno(ret, eventos))
        return resultados
