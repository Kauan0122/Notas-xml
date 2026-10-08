from notaxml.manifestacao import interpretar_retorno, montar_evento
from notaxml.xmlutil import parse

from .conftest import CHAVE, CNPJ


def test_interpreta_retorno_e_monta_proc_evento(certificado):
    evento = montar_evento(certificado, 1, CNPJ, CHAVE, "ciencia")
    ret = parse(f"""<retEnvEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00"><idLote>1</idLote>
<tpAmb>1</tpAmb><verAplic>AN</verAplic><cOrgao>91</cOrgao><cStat>128</cStat><xMotivo>Lote de Evento Processado</xMotivo>
<retEvento versao="1.00"><infEvento><tpAmb>1</tpAmb><verAplic>AN</verAplic><cOrgao>91</cOrgao><cStat>135</cStat>
<xMotivo>Evento registrado e vinculado a NF-e</xMotivo><chNFe>{CHAVE}</chNFe><tpEvento>210210</tpEvento>
<nSeqEvento>1</nSeqEvento><nProt>891260000000001</nProt></infEvento></retEvento></retEnvEvento>""".encode())

    [r] = interpretar_retorno(ret, [evento])
    assert r.sucesso and r.protocolo == "891260000000001"
    proc = parse(r.xml_proc)
    assert proc.tag.endswith("procEventoNFe") and len(proc) == 2
