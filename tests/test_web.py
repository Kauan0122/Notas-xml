import io
import re
from datetime import date, datetime
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from notaxml.armazenamento import Armazenamento
from notaxml.config import Config, ConfigWeb
from notaxml.manifestacao import EVENTOS, ResultadoEvento
from notaxml.sincronizador import Sincronizador
from notaxml.web import criar_app
from notaxml.web.tarefas import GerenciadorTarefas

from .conftest import CHAVE, CNPJ, proc_nfe, res_nfe, ret_dist
from .test_sincronizador import DistFalsa

OUTRA = CHAVE[:-1] + "7"


class ManifestacaoFalsa:
    def __init__(self):
        self.enviados = []

    def enviar(self, chaves, tipo, justificativa=None):
        self.enviados.append((chaves, tipo, justificativa))
        return [ResultadoEvento(c, EVENTOS[tipo][0], "135", "Evento registrado", "1", None) for c in chaves]


def _config(tmp_path: Path, arquivo_pfx, senha_web=None, senha_cert="1234") -> Config:
    return Config(documento=CNPJ, uf="SP", certificado=arquivo_pfx, senha=senha_cert, ambiente=1,
                  verificar_ssl=True, timeout=5, pasta_dados=tmp_path / "dados", ciencia_automatica=False,
                  web=ConfigWeb(senha=senha_web))


@pytest.fixture
def ambiente(tmp_path, arquivo_pfx):
    def criar(senha_web=None, senha_cert="1234", respostas=()):
        cfg = _config(tmp_path, arquivo_pfx, senha_web, senha_cert)
        dist = DistFalsa(respostas)
        manif = ManifestacaoFalsa()

        @contextmanager
        def abrir(cfg_, cert, log):
            banco = Armazenamento(cfg_.pasta_dados)
            try:
                yield Sincronizador(dist, banco, manif, log=log)
            finally:
                banco.fechar()

        gerenciador = GerenciadorTarefas(cfg, abrir_sessao=abrir)
        app = criar_app(cfg, gerenciador)
        app.testing = True
        return app, gerenciador, dist, manif, cfg
    return criar


def _popular(cfg):
    banco = Armazenamento(cfg.pasta_dados)
    banco.guardar("resNFe", res_nfe().encode())
    banco.guardar("procNFe", proc_nfe().encode())
    banco.guardar("resNFe", res_nfe(chave=OUTRA, valor="99.90").encode())
    banco.fechar()


def _csrf(cliente) -> str:
    html = cliente.get("/").get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _esperar(gerenciador):
    gerenciador.atual.thread.join(5)
    assert gerenciador.atual.situacao == "concluida", gerenciador.atual.linhas


def test_lista_e_detalhes(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular(cfg)
    cliente = app.test_client()

    html = cliente.get("/").get_data(as_text=True)
    assert "FORNECEDOR SA" in html and "R$ 1.500,00" in html and "R$ 99,90" in html
    assert "Certificado ativo" in html

    html = cliente.get("/?q=nada-disso").get_data(as_text=True)
    assert "Nenhuma nota com esses filtros" in html
    html = cliente.get("/?pendencia=sem_xml").get_data(as_text=True)
    assert "R$ 99,90" in html and "R$ 1.500,00" not in html.split("<tbody>")[1]

    html = cliente.get(f"/nota/{CHAVE}").get_data(as_text=True)
    assert "Baixar XML da NF-e" in html and "3526 1099" in html
    assert cliente.get("/nota/123").status_code == 404


def test_downloads(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular(cfg)
    cliente = app.test_client()

    r = cliente.get(f"/nota/{CHAVE}/nfe.xml")
    assert r.status_code == 200 and b"<nfeProc" in r.data
    assert cliente.get(f"/nota/{OUTRA}/nfe.xml").status_code == 404
    assert cliente.get(f"/nota/{CHAVE}/qualquer.xml").status_code == 404

    r = cliente.get("/exportar.csv")
    texto = r.data.decode("utf-8-sig")
    assert texto.startswith("chave;") and "99,90" in texto

    r = cliente.get("/exportar.zip")
    nomes = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert nomes == [f"{CHAVE}-nfe.xml"]


def test_post_sem_csrf_e_recusado(ambiente):
    app, gerenciador, *_ = ambiente()
    r = app.test_client().post("/acoes/sincronizar", data={})
    assert r.status_code == 400 and gerenciador.atual is None


def test_sincronizar_em_segundo_plano(ambiente):
    respostas = [ret_dist("138", "000000000000001", "000000000000001",
                          [("000000000000001", "resNFe_v1.01.xsd", res_nfe())])]
    app, gerenciador, dist, manif, _ = ambiente(respostas=respostas)
    cliente = app.test_client()
    r = cliente.post("/acoes/sincronizar", data={"csrf": _csrf(cliente), "ciencia": "1"})
    assert r.status_code == 302
    _esperar(gerenciador)
    assert dist.pedidos == ["000000000000000"]
    assert manif.enviados == [([CHAVE], "ciencia", None)]

    estado = cliente.get("/tarefa").get_json()
    assert estado["situacao"] == "concluida" and any("Ciência" in l for l in estado["linhas"])
    assert "Ciência da Operação" in cliente.get("/").get_data(as_text=True)


def test_manifestar_selecionadas_valida_justificativa(ambiente):
    app, gerenciador, _, manif, cfg = ambiente()
    _popular(cfg)
    cliente = app.test_client()
    csrf = _csrf(cliente)

    r = cliente.post("/acoes/selecionadas", data={"csrf": csrf, "chave": [OUTRA], "acao": "manifestar",
                                                  "evento": "nao-realizada", "justificativa": "curta"},
                     follow_redirects=True)
    assert "exige justificativa" in r.get_data(as_text=True) and gerenciador.atual is None

    cliente.post("/acoes/selecionadas", data={"csrf": csrf, "chave": [OUTRA], "acao": "manifestar",
                                              "evento": "confirmacao"})
    _esperar(gerenciador)
    assert manif.enviados == [([OUTRA], "confirmacao", None)]

    r = cliente.post("/acoes/selecionadas", data={"csrf": csrf, "chave": [CHAVE, OUTRA], "acao": "zip"})
    assert zipfile.ZipFile(io.BytesIO(r.data)).namelist() == [f"{CHAVE}-nfe.xml"]


def test_redirecionamento_externo_bloqueado(ambiente):
    app, *_ = ambiente()
    cliente = app.test_client()
    r = cliente.post("/acoes/selecionadas", data={"csrf": _csrf(cliente), "voltar": "//malicioso.com"})
    assert r.headers["Location"] == "/"


def test_login_obrigatorio_quando_ha_senha(ambiente):
    app, *_ = ambiente(senha_web="segredo")
    cliente = app.test_client()
    r = cliente.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert cliente.get(f"/nota/{CHAVE}/nfe.xml").status_code == 302

    html = cliente.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    r = cliente.post("/login", data={"csrf": csrf, "senha": "errada"}, follow_redirects=True)
    assert "Senha incorreta" in r.get_data(as_text=True)
    r = cliente.post("/login", data={"csrf": csrf, "senha": "segredo"})
    assert r.status_code == 302 and cliente.get("/").status_code == 200


def test_desbloquear_certificado_pela_tela(ambiente):
    app, gerenciador, *_ = ambiente(senha_cert=None)
    cliente = app.test_client()
    assert gerenciador.certificado is None
    assert "Certificado bloqueado" in cliente.get("/").get_data(as_text=True)

    csrf = _csrf(cliente)
    r = cliente.post("/certificado", data={"csrf": csrf, "senha": "errada"}, follow_redirects=True)
    assert "senha incorreta" in r.get_data(as_text=True)
    r = cliente.post("/certificado", data={"csrf": csrf, "senha": "1234"}, follow_redirects=True)
    assert "EMPRESA TESTE LTDA" in r.get_data(as_text=True) and gerenciador.certificado is not None


def test_sincronizacao_automatica_respeita_intervalo(ambiente):
    app, gerenciador, dist, *_ = ambiente(respostas=[ret_dist("137", "000000000000000", "000000000000000")])
    tarefa = gerenciador.verificar_agenda()
    assert tarefa is not None
    tarefa.thread.join(5)
    assert dist.pedidos == ["000000000000000"]
    assert gerenciador.verificar_agenda() is None  # SEFAZ pede 1 hora


# ---- DANFE ------------------------------------------------------------------

def _popular_completa(cfg):
    from .nfe_exemplo import CHAVE_COMPLETA, nfe_completa

    banco = Armazenamento(cfg.pasta_dados)
    banco.guardar("procNFe", nfe_completa().encode())
    banco.fechar()
    return CHAVE_COMPLETA


def test_danfe_da_nota(ambiente):
    app, _, _, _, cfg = ambiente()
    chave = _popular_completa(cfg)
    cliente = app.test_client()

    r = cliente.get(f"/nota/{chave}/danfe.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert "attachment" not in r.headers.get("Content-Disposition", "")  # abre no navegador

    r = cliente.get(f"/nota/{chave}/danfe.pdf?baixar=1")
    assert f"DANFE-{chave}.pdf" in r.headers["Content-Disposition"] and "attachment" in r.headers["Content-Disposition"]

    html = cliente.get("/").get_data(as_text=True)
    assert f"/nota/{chave}/danfe.pdf" in html
    assert "Ver DANFE" in cliente.get(f"/nota/{chave}").get_data(as_text=True)


def test_danfe_sem_xml_completo(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular(cfg)  # OUTRA só tem resumo
    r = app.test_client().get(f"/nota/{OUTRA}/danfe.pdf")
    assert r.status_code == 404 and "ainda não foi baixado" in r.get_data(as_text=True)
    assert app.test_client().get("/nota/123/danfe.pdf").status_code == 404


def test_danfe_de_xml_invalido_mostra_erro(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular(cfg)  # proc_nfe mínimo da fixture não tem dados suficientes para um DANFE
    r = app.test_client().get(f"/nota/{CHAVE}/danfe.pdf")
    assert r.status_code == 400 and "Não foi possível gerar o DANFE" in r.get_data(as_text=True)


def test_zip_de_danfes_das_selecionadas(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular(cfg)
    chave = _popular_completa(cfg)
    cliente = app.test_client()
    csrf = _csrf(cliente)

    r = cliente.post("/acoes/selecionadas", data={"csrf": csrf, "acao": "danfe", "chave": [chave, OUTRA, CHAVE]})
    assert r.mimetype == "application/zip"
    arquivos = zipfile.ZipFile(io.BytesIO(r.data))
    assert arquivos.namelist() == [f"DANFE-{chave}.pdf"]  # resumo e XML inválido ficam de fora
    assert arquivos.read(arquivos.namelist()[0]).startswith(b"%PDF")

    r = cliente.post("/acoes/selecionadas", data={"csrf": csrf, "acao": "danfe", "chave": [OUTRA]},
                     follow_redirects=True)
    assert "Nenhuma das notas escolhidas" in r.get_data(as_text=True)


# ---- contas a pagar -----------------------------------------------------------

def _popular_com_parcelas(cfg):
    from datetime import timedelta

    from .nfe_exemplo import CHAVE_COMPLETA
    from .test_titulos import _com_parcelas

    hoje = date.today()
    banco = Armazenamento(cfg.pasta_dados)
    banco.guardar("procNFe", _com_parcelas([
        ("001", (hoje - timedelta(days=3)).isoformat(), "500.00"),
        ("002", hoje.isoformat(), "300.00"),
        ("003", (hoje + timedelta(days=40)).isoformat(), "775.00"),
    ]).encode())
    banco.fechar()
    return CHAVE_COMPLETA


def test_tela_de_contas_a_pagar(ambiente):
    app, _, _, _, cfg = ambiente()
    chave = _popular_com_parcelas(cfg)
    cliente = app.test_client()

    html = cliente.get("/pagar").get_data(as_text=True)
    assert "Contas a pagar" in html and "FORNECEDOR SA" in html
    assert "R$ 500,00" in html and "R$ 775,00" in html
    assert "vencido" in html                       # parcela atrasada destacada
    assert 'class="contador"' in cliente.get("/").get_data(as_text=True)  # aviso no menu (1 vencido + 1 hoje)

    # filtros: só o que vence nos próximos dias e pagos
    ate_hoje = cliente.get("/pagar?de=2000-01-01&ate=" + date.today().isoformat()).get_data(as_text=True)
    assert "R$ 775,00" not in ate_hoje.split("<tbody>")[1]
    assert "Nenhum título com esses filtros" in cliente.get("/pagar?situacao=pago").get_data(as_text=True)
    assert f"/nota/{chave}" in html


def test_marcar_como_pago_reabrir_e_excluir(ambiente):
    app, _, _, _, cfg = ambiente()
    chave = _popular_com_parcelas(cfg)
    cliente = app.test_client()
    csrf = _csrf(cliente)

    banco = Armazenamento(cfg.pasta_dados)
    ids = [t["id"] for t in banco.titulos()]
    banco.fechar()

    r = cliente.post("/pagar/acao", data={"csrf": csrf, "acao": "pagar", "id": ids[:2], "data_pagamento": "2026-10-10"},
                     follow_redirects=True)
    assert "2 título(s) marcado(s) como pago(s)" in r.get_data(as_text=True)
    banco = Armazenamento(cfg.pasta_dados)
    assert [t["situacao"] for t in banco.titulos()] == ["pago", "pago", "aberto"]
    assert banco.titulos()[0]["pago_em"] == "2026-10-10"
    banco.fechar()

    assert "Informe a data do pagamento" in cliente.post(
        "/pagar/acao", data={"csrf": csrf, "acao": "pagar", "id": ids[2], "data_pagamento": "10/10/2026"},
        follow_redirects=True).get_data(as_text=True)

    cliente.post("/pagar/acao", data={"csrf": csrf, "acao": "reabrir", "id": ids[:1]})
    banco = Armazenamento(cfg.pasta_dados)
    assert [t["situacao"] for t in banco.titulos()] == ["aberto", "pago", "aberto"]
    banco.fechar()

    # parcela que veio da nota não pode ser excluída; lançamento manual pode
    cliente.post(f"/nota/{chave}/titulo", data={"csrf": csrf, "vencimento": "2026-12-25", "valor": "1.234,56",
                                                 "observacao": "frete"})
    banco = Armazenamento(cfg.pasta_dados)
    manual = [t for t in banco.titulos() if t["origem"] == "manual"][0]
    assert manual["valor"] == 1234.56 and manual["observacao"] == "frete"
    banco.fechar()
    cliente.post("/pagar/acao", data={"csrf": csrf, "acao": "excluir", "id": [ids[0], manual["id"]]})
    banco = Armazenamento(cfg.pasta_dados)
    assert len(banco.titulos()) == 3 and all(t["origem"] == "nota" for t in banco.titulos())
    banco.fechar()


def test_lancamento_manual_valida_os_campos(ambiente):
    app, _, _, _, cfg = ambiente()
    chave = _popular_com_parcelas(cfg)
    cliente = app.test_client()
    csrf = _csrf(cliente)
    r = cliente.post(f"/nota/{chave}/titulo", data={"csrf": csrf, "vencimento": "2026-12-25", "valor": "abc"},
                     follow_redirects=True)
    assert "Valor inválido" in r.get_data(as_text=True)
    r = cliente.post("/pagar/acao", data={"csrf": csrf, "acao": "pagar", "id": "x"})
    assert r.status_code == 400
    assert "Selecione ao menos um título" in cliente.post(
        "/pagar/acao", data={"csrf": csrf, "acao": "pagar"}, follow_redirects=True).get_data(as_text=True)
    assert "Parcela lançada" in cliente.post(
        f"/nota/{chave}/titulo", data={"csrf": csrf, "vencimento": "2026-12-25", "valor": "10"},
        follow_redirects=True).get_data(as_text=True)
    page = cliente.get(f"/nota/{chave}").get_data(as_text=True)
    assert "Contas a pagar desta nota" in page and "lançada à mão" in page


def test_csv_de_contas_a_pagar(ambiente):
    app, _, _, _, cfg = ambiente()
    _popular_com_parcelas(cfg)
    r = app.test_client().get("/pagar.csv")
    texto = r.data.decode("utf-8-sig")
    assert r.mimetype == "text/csv" and texto.startswith("fornecedor;cnpj;nota;parcela;vencimento;valor")
    assert texto.count("\n") == 4 and "500,00" in texto


# ---- navegação estilo WhatsApp (celular) -------------------------------------------------------------------

def test_abas_inferiores_e_avatares(ambiente):
    from notaxml.web import _iniciais, _matiz

    assert _iniciais("ATACADAO DE EMBALAGENS SA") == "AE"
    assert _iniciais("Transportes Rápido Sul Ltda") == "TR"
    assert _iniciais("") == "?" and _iniciais(None) == "?"
    assert _iniciais("3M DO BRASIL") == "3B"
    assert _matiz("FORNECEDOR SA") == _matiz("FORNECEDOR SA") and 0 <= _matiz("FORNECEDOR SA") < 360
    assert _matiz("A") != _matiz("B")

    app, _, _, _, cfg = ambiente()
    _popular_com_parcelas(cfg)
    cliente = app.test_client()
    html = cliente.get("/").get_data(as_text=True)
    assert 'class="abas"' in html and html.count('class="aba ') == 3  # Notas, Contas, Certificado (Ajustes só existe no app com configuração)
    assert 'class="aba ativa"' in html and 'class="avatar"' in html and "<span>F</span>" in html
    assert 'class="contador">2<' in html.split('class="abas"')[1]  # o aviso de contas vencidas também nas abas

    assert 'class="topo-mobile"' in html and "<h2 class=\"titulo-mobile\">Notas</h2>" in html
    pagar = cliente.get("/pagar").get_data(as_text=True)
    assert "<h2 class=\"titulo-mobile\">Contas a pagar</h2>" in pagar and "lista-conversas" in pagar
    detalhe = cliente.get("/nota/" + __import__("notaxml.amostra_nfe", fromlist=["x"]).CHAVE_COMPLETA).get_data(as_text=True)
    assert 'class="voltar"' in detalhe  # a nota abre como uma conversa, com seta de voltar


def test_login_nao_mostra_abas(ambiente):
    app, *_ = ambiente(senha_web="segredo")
    html = app.test_client().get("/login").get_data(as_text=True)
    assert 'class="abas"' not in html and "topo-mobile" not in html


def test_datas_e_rotulos_curtos(ambiente):
    from notaxml.web import _data_curta

    hoje = date.today()
    assert _data_curta(hoje.isoformat()) == hoje.strftime("%d/%m")
    assert _data_curta("2020-03-09T10:00:00-03:00") == "09/03/20"
    assert _data_curta("lixo") == "lixo"

    app, _, _, _, cfg = ambiente()
    _popular_com_parcelas(cfg)
    banco = Armazenamento(cfg.pasta_dados)
    banco.registrar_manifestacao(__import__("notaxml.amostra_nfe", fromlist=["x"]).CHAVE_COMPLETA, "210200")
    banco.fechar()
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'class="so-movel">Confirmada<' in html and 'class="nao-movel">Confirmação da Operação<' in html


def test_hora_curta_e_resumo_da_sincronizacao_no_celular(ambiente):
    from datetime import timezone

    from notaxml.web import _hora_curta

    agora = datetime.now(timezone.utc)
    assert _hora_curta(agora.isoformat()) == agora.astimezone().strftime("%H:%M")
    assert _hora_curta("2020-03-09T10:00:00-03:00").startswith("09/03 ")
    assert _hora_curta("lixo") == "lixo"

    app, _, _, _, cfg = ambiente()
    banco = Armazenamento(cfg.pasta_dados)
    banco.salvar_nsu(CNPJ, 1, "000000000000866", "000000000000866")
    banco.aguardar(CNPJ, 1)
    banco.fechar()
    html = app.test_client().get("/").get_data(as_text=True)
    assert "NSU 866/866 · próxima consulta" in html and 'class="muted so-movel-bloco"' in html
