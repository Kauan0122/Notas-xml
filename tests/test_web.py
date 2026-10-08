import io
import re
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
