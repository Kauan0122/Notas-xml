from lxml import etree

NS_NFE = "http://www.portalfiscal.inf.br/nfe"
NS = {"n": NS_NFE}

# Parser seguro para XML vindo de fora (sem entidades externas nem rede).
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True, huge_tree=True)


def parse(dados: bytes) -> etree._Element:
    return etree.fromstring(dados, parser=_PARSER)


def el(tag: str, texto: str | None = None, **attrs) -> etree._Element:
    elemento = etree.Element(f"{{{NS_NFE}}}{tag}", nsmap={None: NS_NFE}, **attrs)
    if texto is not None:
        elemento.text = texto
    return elemento


def sub(pai: etree._Element, tag: str, texto: str | None = None, **attrs) -> etree._Element:
    elemento = etree.SubElement(pai, f"{{{NS_NFE}}}{tag}", **attrs)
    if texto is not None:
        elemento.text = texto
    return elemento


def texto(elemento: etree._Element, caminho: str) -> str | None:
    valor = elemento.findtext(caminho, namespaces=NS)
    return valor.strip() if valor is not None else None


def serializar(elemento: etree._Element) -> bytes:
    return etree.tostring(elemento, encoding="utf-8")
