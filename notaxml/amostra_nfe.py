"""NF-e completa de exemplo (dados fictícios): usada nos testes e no autoteste do aplicativo Android."""


def _dv(base43: str) -> str:
    soma, peso = 0, 2
    for d in reversed(base43):
        soma += int(d) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


_BASE = "3526109999999900019955001000001234100012345"
CHAVE_COMPLETA = _BASE + _dv(_BASE)


def nfe_completa(chave: str = CHAVE_COMPLETA, cstat: str = "100") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><cUF>35</cUF><cNF>00012345</cNF><natOp>VENDA DE MERCADORIA</natOp><mod>55</mod><serie>1</serie><nNF>1234</nNF>
<dhEmi>2026-10-01T10:00:00-03:00</dhEmi><dhSaiEnt>2026-10-01T11:00:00-03:00</dhSaiEnt><tpNF>1</tpNF><idDest>1</idDest>
<cMunFG>3550308</cMunFG><tpImp>1</tpImp><tpEmis>1</tpEmis><cDV>{chave[-1]}</cDV><tpAmb>1</tpAmb><finNFe>1</finNFe>
<indFinal>0</indFinal><indPres>1</indPres><procEmi>0</procEmi><verProc>1.0</verProc></ide>
<emit><CNPJ>99999999000199</CNPJ><xNome>FORNECEDOR SA</xNome><xFant>FORNECEDOR</xFant>
<enderEmit><xLgr>RUA DAS FLORES</xLgr><nro>100</nro><xBairro>CENTRO</xBairro><cMun>3550308</cMun><xMun>SAO PAULO</xMun>
<UF>SP</UF><CEP>01001000</CEP><cPais>1058</cPais><xPais>BRASIL</xPais><fone>1133334444</fone></enderEmit>
<IE>123456789012</IE><CRT>3</CRT></emit>
<dest><CNPJ>11222333000181</CNPJ><xNome>EMPRESA TESTE LTDA</xNome>
<enderDest><xLgr>AV BRASIL</xLgr><nro>500</nro><xBairro>JARDIM</xBairro><cMun>3550308</cMun><xMun>SAO PAULO</xMun>
<UF>SP</UF><CEP>01310100</CEP><cPais>1058</cPais><xPais>BRASIL</xPais></enderDest><indIEDest>1</indIEDest><IE>987654321098</IE></dest>
<det nItem="1"><prod><cProd>001</cProd><cEAN>SEM GTIN</cEAN><xProd>PARAFUSO SEXTAVADO 10MM</xProd><NCM>73181500</NCM>
<CFOP>5102</CFOP><uCom>CX</uCom><qCom>10.0000</qCom><vUnCom>100.0000000000</vUnCom><vProd>1000.00</vProd><cEANTrib>SEM GTIN</cEANTrib>
<uTrib>CX</uTrib><qTrib>10.0000</qTrib><vUnTrib>100.0000000000</vUnTrib><indTot>1</indTot></prod>
<imposto><ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC><vBC>1000.00</vBC><pICMS>18.00</pICMS><vICMS>180.00</vICMS></ICMS00></ICMS>
<IPI><cEnq>999</cEnq><IPITrib><CST>50</CST><vBC>1000.00</vBC><pIPI>5.00</pIPI><vIPI>50.00</vIPI></IPITrib></IPI>
<PIS><PISAliq><CST>01</CST><vBC>1000.00</vBC><pPIS>1.65</pPIS><vPIS>16.50</vPIS></PISAliq></PIS>
<COFINS><COFINSAliq><CST>01</CST><vBC>1000.00</vBC><pCOFINS>7.60</pCOFINS><vCOFINS>76.00</vCOFINS></COFINSAliq></COFINS></imposto></det>
<det nItem="2"><prod><cProd>002</cProd><cEAN>SEM GTIN</cEAN><xProd>PORCA SEXTAVADA 10MM</xProd><NCM>73181600</NCM>
<CFOP>5102</CFOP><uCom>CX</uCom><qCom>5.0000</qCom><vUnCom>100.0000000000</vUnCom><vProd>500.00</vProd><cEANTrib>SEM GTIN</cEANTrib>
<uTrib>CX</uTrib><qTrib>5.0000</qTrib><vUnTrib>100.0000000000</vUnTrib><indTot>1</indTot></prod>
<imposto><ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC><vBC>500.00</vBC><pICMS>18.00</pICMS><vICMS>90.00</vICMS></ICMS00></ICMS>
<IPI><cEnq>999</cEnq><IPITrib><CST>50</CST><vBC>500.00</vBC><pIPI>5.00</pIPI><vIPI>25.00</vIPI></IPITrib></IPI>
<PIS><PISAliq><CST>01</CST><vBC>500.00</vBC><pPIS>1.65</pPIS><vPIS>8.25</vPIS></PISAliq></PIS>
<COFINS><COFINSAliq><CST>01</CST><vBC>500.00</vBC><pCOFINS>7.60</pCOFINS><vCOFINS>38.00</vCOFINS></COFINSAliq></COFINS></imposto></det>
<total><ICMSTot><vBC>1500.00</vBC><vICMS>270.00</vICMS><vICMSDeson>0.00</vICMSDeson><vFCP>0.00</vFCP><vBCST>0.00</vBCST><vST>0.00</vST>
<vFCPST>0.00</vFCPST><vFCPSTRet>0.00</vFCPSTRet><vProd>1500.00</vProd><vFrete>0.00</vFrete><vSeg>0.00</vSeg><vDesc>0.00</vDesc>
<vII>0.00</vII><vIPI>75.00</vIPI><vIPIDevol>0.00</vIPIDevol><vPIS>24.75</vPIS><vCOFINS>114.00</vCOFINS><vOutro>0.00</vOutro>
<vNF>1575.00</vNF></ICMSTot></total>
<transp><modFrete>0</modFrete><transporta><CNPJ>44555666000154</CNPJ><xNome>TRANSPORTES RAPIDO SUL LTDA</xNome>
<IE>111222333444</IE><xEnder>RUA DO FRETE 1</xEnder><xMun>SAO PAULO</xMun><UF>SP</UF></transporta>
<vol><qVol>15</qVol><esp>CAIXA</esp><pesoL>30.000</pesoL><pesoB>32.000</pesoB></vol></transp>
<cobr><fat><nFat>1234</nFat><vOrig>1575.00</vOrig><vLiq>1575.00</vLiq></fat><dup><nDup>001</nDup><dVenc>2026-11-01</dVenc><vDup>1575.00</vDup></dup></cobr>
<pag><detPag><tPag>15</tPag><vPag>1575.00</vPag></detPag></pag>
<infAdic><infCpl>Pedido de compra 4567. Documento emitido por ME ou EPP optante pelo Simples Nacional.</infCpl></infAdic>
</infNFe></NFe>
<protNFe versao="4.00"><infProt><tpAmb>1</tpAmb><verAplic>SP_NFE_PL009_V4</verAplic><chNFe>{chave}</chNFe>
<dhRecbto>2026-10-01T10:00:05-03:00</dhRecbto><nProt>135260000000001</nProt><digVal>abc=</digVal><cStat>{cstat}</cStat>
<xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe></nfeProc>"""
