import pytest

from notaxml.armazenamento import Armazenamento
from notaxml.distribuicao import interpretar_retorno
from notaxml.erros import ErroSefaz
from notaxml.sincronizador import Sincronizador
from notaxml.xmlutil import parse

from .conftest import CHAVE, CNPJ, proc_evento_cancelamento, proc_nfe, res_nfe, ret_dist

OUTRA = CHAVE[:-1] + "9"


class DistFalsa:
    documento = CNPJ
    ambiente = 1

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def consultar_nsu(self, ult_nsu):
        self.pedidos.append(ult_nsu)
        return interpretar_retorno(parse(self.respostas.pop(0).encode()))


@pytest.fixture
def banco(tmp_path):
    b = Armazenamento(tmp_path / "dados")
    yield b
    b.fechar()


def test_sincroniza_ate_max_nsu_e_respeita_intervalo(banco):
    dist = DistFalsa([
        ret_dist("138", "000000000000001", "000000000000002", [("000000000000001", "resNFe_v1.01.xsd", res_nfe())]),
        ret_dist("138", "000000000000002", "000000000000002", [("000000000000002", "procNFe_v4.00.xsd", proc_nfe())]),
    ])
    sinc = Sincronizador(dist, banco, log=lambda _: None)
    resumo = sinc.sincronizar()

    assert dist.pedidos == ["000000000000000", "000000000000001"]
    assert resumo.documentos == {"resNFe": 1, "procNFe": 1}
    assert banco.estado(CNPJ, 1).ult_nsu == "000000000000002"

    nota = banco.listar()[0]
    assert nota["chave"] == CHAVE and nota["valor"] == 1500.0 and nota["situacao"] == "autorizada"
    assert (banco.pasta / nota["arquivo_xml"]).is_file()
    assert nota["arquivo_xml"].startswith("xml/nfe/2026-10/")

    # segunda execução dentro de 1 hora não consulta a SEFAZ
    assert sinc.sincronizar().bloqueado
    assert len(dist.pedidos) == 2


def test_continua_do_ultimo_nsu(banco):
    banco.salvar_nsu(CNPJ, 1, "000000000000050", "000000000000050")
    dist = DistFalsa([ret_dist("137", "000000000000050", "000000000000050")])
    Sincronizador(dist, banco, log=lambda _: None).sincronizar()
    assert dist.pedidos == ["000000000000050"]


def test_consumo_indevido_bloqueia(banco):
    dist = DistFalsa([ret_dist("656", "000000000000000", "000000000000000")])
    with pytest.raises(ErroSefaz) as exc:
        Sincronizador(dist, banco, log=lambda _: None).sincronizar()
    assert exc.value.cstat == "656"
    assert banco.estado(CNPJ, 1).proxima_consulta is not None


def test_pendencias_de_manifestacao_e_cancelamento(banco):
    banco.guardar("resNFe", res_nfe().encode())
    banco.guardar("resNFe", res_nfe(chave=OUTRA).encode())
    assert set(banco.chaves_sem_manifestacao()) == {CHAVE, OUTRA}

    banco.registrar_manifestacao(CHAVE, "210210")
    assert banco.chaves_sem_manifestacao() == [OUTRA]
    assert banco.chaves_aguardando_xml() == [CHAVE]

    banco.guardar("procEventoNFe", proc_evento_cancelamento(OUTRA).encode())
    assert banco.chaves_sem_manifestacao() == []

    banco.guardar("procNFe", proc_nfe().encode())
    assert banco.chaves_aguardando_xml() == []
    assert len(banco.listar(somente_pendentes=True)) == 1
