import io
from datetime import date

import pytest

from notaxml.armazenamento import Armazenamento
from notaxml.titulos import (ErroTitulo, FiltroTitulos, classificar, escrever_csv, ler_data, ler_duplicatas,
                             ler_valor)
from notaxml.xmlutil import NS, parse

from .conftest import proc_evento_cancelamento
from .nfe_exemplo import CHAVE_COMPLETA, nfe_completa

HOJE = date(2026, 10, 15)


def _com_parcelas(parcelas: list[tuple[str, str, str]], cstat: str = "100") -> str:
    """NF-e de exemplo com as duplicatas trocadas por `parcelas` = [(nDup, dVenc, vDup)]."""
    xml = nfe_completa(cstat=cstat)
    inicio, fim = xml.index("<cobr>"), xml.index("</cobr>") + len("</cobr>")
    dups = "".join(f"<dup><nDup>{n}</nDup><dVenc>{v}</dVenc><vDup>{d}</vDup></dup>" for n, v, d in parcelas)
    return xml[:inicio] + f"<cobr><fat><nFat>1</nFat><vOrig>1575.00</vOrig></fat>{dups}</cobr>" + xml[fim:]


@pytest.fixture
def banco(tmp_path):
    b = Armazenamento(tmp_path / "dados")
    yield b
    b.fechar()


def test_ler_duplicatas_da_nota():
    inf = parse(_com_parcelas([("001", "2026-11-01", "500.00"), ("002", "2026-12-01", "500.00"),
                               ("003", "2026-12-31", "575.00")]).encode()).find(".//n:infNFe", namespaces=NS)
    assert [(d.parcela, d.vencimento, d.valor) for d in ler_duplicatas(inf)] == [
        ("001", "2026-11-01", 500.0), ("002", "2026-12-01", 500.0), ("003", "2026-12-31", 575.0)]


def test_parcelas_invalidas_ou_repetidas():
    inf = parse(_com_parcelas([("1", "2026-11-01", "10.00"), ("1", "2026-12-01", "10.00"),
                               ("3", "data-ruim", "10.00"), ("4", "2027-01-01", "abc")]).encode()).find(
        ".//n:infNFe", namespaces=NS)
    parcelas = [d.parcela for d in ler_duplicatas(inf)]
    assert len(parcelas) == 2 and len(set(parcelas)) == 2  # as inválidas ficam de fora; a repetida ganha sufixo


def test_nota_gera_titulos_uma_unica_vez(banco):
    xml = _com_parcelas([("001", "2026-10-20", "500.00"), ("002", "2026-11-20", "1075.00")]).encode()
    banco.guardar("procNFe", xml)
    banco.guardar("procNFe", xml)  # chegando de novo (reprocessamento): não duplica

    titulos = banco.titulos()
    assert [(t["parcela"], t["vencimento"], t["valor"], t["situacao"]) for t in titulos] == [
        ("001", "2026-10-20", 500.0, "aberto"), ("002", "2026-11-20", 1075.0, "aberto")]
    assert titulos[0]["emitente_nome"] == "FORNECEDOR SA" and titulos[0]["numero"] == "1234"

    banco.marcar_pago([titulos[0]["id"]], HOJE)
    banco.guardar("procNFe", xml)  # e o que já foi pago continua pago
    assert [t["situacao"] for t in banco.titulos()] == ["pago", "aberto"]


def test_nota_sem_duplicatas_nao_gera_titulos_mas_aceita_lancamento_manual(banco):
    xml = nfe_completa()
    xml = xml[:xml.index("<cobr>")] + xml[xml.index("</cobr>") + len("</cobr>"):]
    banco.guardar("procNFe", xml.encode())
    assert banco.titulos() == []

    id1 = banco.adicionar_titulo(CHAVE_COMPLETA, "2026-10-30", 1575.0, "  pix combinado  ")
    banco.adicionar_titulo(CHAVE_COMPLETA, "2026-11-30", 10.0)
    manuais = banco.titulos()
    assert [t["parcela"] for t in manuais] == ["M1", "M2"] and manuais[0]["observacao"] == "pix combinado"
    assert banco.excluir_titulos_manuais([id1]) == 1 and len(banco.titulos()) == 1
    with pytest.raises(ErroTitulo):
        banco.adicionar_titulo("0" * 44, "2026-10-30", 1.0)


def test_cancelamento_e_desconhecimento_cancelam_so_o_que_esta_em_aberto(banco):
    banco.guardar("procNFe", _com_parcelas([("1", "2026-10-20", "100.00"), ("2", "2026-11-20", "200.00")]).encode())
    banco.marcar_pago([banco.titulos()[0]["id"]], HOJE)

    banco.guardar("procEventoNFe", proc_evento_cancelamento(CHAVE_COMPLETA).encode())
    assert [t["situacao"] for t in banco.titulos()] == ["pago", "cancelado"]  # o pago fica como está


def test_cancelamento_antes_do_xml_completo_nao_gera_titulos(banco):
    banco.guardar("procEventoNFe", proc_evento_cancelamento(CHAVE_COMPLETA).encode())
    banco.guardar("procNFe", nfe_completa().encode())
    assert banco.nota(CHAVE_COMPLETA)["situacao"] == "cancelada" and banco.titulos() == []


def test_desconhecimento_da_operacao_cancela_os_titulos(banco):
    banco.guardar("procNFe", nfe_completa().encode())
    assert banco.titulos()[0]["situacao"] == "aberto"
    banco.registrar_manifestacao(CHAVE_COMPLETA, "210220")
    assert banco.titulos()[0]["situacao"] == "cancelado"

    banco.reabrir([banco.titulos()[0]["id"]])  # dá para reabrir se foi engano
    assert banco.titulos()[0]["situacao"] == "aberto"


def test_nota_denegada_nao_gera_titulos(banco):
    banco.guardar("procNFe", nfe_completa(cstat="110").encode())
    assert banco.titulos() == []


def test_banco_de_versao_anterior_e_atualizado(tmp_path):
    import sqlite3

    pasta = tmp_path / "dados"
    banco = Armazenamento(pasta)
    banco.guardar("procNFe", nfe_completa().encode())
    banco.fechar()

    # simula um banco criado antes do contas a pagar: sem a tabela de títulos e sem as colunas novas
    db = sqlite3.connect(pasta / "notas.db")
    db.execute("DROP TABLE titulos")
    db.execute("ALTER TABLE notas DROP COLUMN numero")
    db.execute("ALTER TABLE notas DROP COLUMN serie")
    db.execute("ALTER TABLE notas DROP COLUMN titulos_lidos")
    db.commit()
    db.close()

    banco = Armazenamento(pasta)  # ao abrir, lê os XMLs que já estavam no disco
    try:
        assert [(t["parcela"], t["valor"]) for t in banco.titulos()] == [("001", 1575.0)]
        assert banco.nota(CHAVE_COMPLETA)["numero"] == "1234"
    finally:
        banco.fechar()


def test_resumo_por_faixa_de_vencimento(banco):
    banco.guardar("procNFe", _com_parcelas([
        ("1", "2026-10-10", "100.00"),   # venceu há 5 dias
        ("2", "2026-10-15", "200.00"),   # hoje
        ("3", "2026-10-20", "300.00"),   # em 5 dias
        ("4", "2026-11-10", "400.00"),   # em 26 dias
        ("5", "2027-03-01", "500.00"),   # longe
        ("6", "2026-10-01", "600.00"),   # vencido, mas será pago
    ]).encode())
    banco.marcar_pago([t["id"] for t in banco.titulos() if t["parcela"] == "6"], HOJE)

    resumo = banco.resumo_titulos(HOJE)
    assert (resumo.vencidos.quantidade, resumo.vencidos.valor) == (1, 100.0)
    assert (resumo.hoje.quantidade, resumo.hoje.valor) == (1, 200.0)
    assert (resumo.proximos_7_dias.quantidade, resumo.proximos_7_dias.valor) == (1, 300.0)
    assert (resumo.proximos_30_dias.quantidade, resumo.proximos_30_dias.valor) == (1, 400.0)
    assert (resumo.total_aberto.quantidade, resumo.total_aberto.valor) == (5, 1500.0)
    assert resumo.atencao == 2


def test_filtros(banco):
    banco.guardar("procNFe", _com_parcelas([("1", "2026-10-10", "100.00"), ("2", "2026-12-10", "200.00")]).encode())
    banco.marcar_pago([banco.titulos()[0]["id"]], HOJE)
    assert len(banco.titulos(FiltroTitulos(situacao="aberto"))) == 1
    assert len(banco.titulos(FiltroTitulos(texto="fornecedor"))) == 2
    assert len(banco.titulos(FiltroTitulos(texto="1234"))) == 2  # número da nota
    assert len(banco.titulos(FiltroTitulos(de="2026-12-01"))) == 1
    assert len(banco.titulos(FiltroTitulos(ate="2026-11-01"))) == 1
    assert banco.titulos(FiltroTitulos(texto="outro")) == []


def test_classificar():
    assert [classificar(d, HOJE) for d in ("2026-10-14", "2026-10-15", "2026-10-22", "2026-10-23", "2026-11-14",
                                          "2026-11-15")] == ["vencido", "hoje", "7dias", "30dias", "30dias", "depois"]


@pytest.mark.parametrize("texto, esperado", [("1.234,56", 1234.56), ("R$ 99,90", 99.9), ("1234.56", 1234.56),
                                              ("10", 10.0), ("0,5", 0.5)])
def test_ler_valor(texto, esperado):
    assert ler_valor(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "0", "-5", "100000000"])
def test_ler_valor_invalido(texto):
    with pytest.raises(ErroTitulo):
        ler_valor(texto)


def test_ler_data():
    assert ler_data("2026-10-30") == "2026-10-30"
    with pytest.raises(ErroTitulo):
        ler_data("30/10/2026", "data de vencimento")


def test_csv(banco):
    banco.guardar("procNFe", _com_parcelas([("001", "2026-11-01", "1234.50")]).encode())
    saida = io.StringIO()
    escrever_csv(saida, banco.titulos())
    linhas = saida.getvalue().strip().splitlines()
    assert linhas[0].startswith("fornecedor;cnpj;nota;parcela;vencimento;valor")
    assert linhas[1].startswith("FORNECEDOR SA;99999999000199;1234/1;001;01/11/2026;1234,50;aberto")
