"""Execução das operações da SEFAZ em segundo plano, uma de cada vez, e agendamento automático."""

import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import operacoes
from ..armazenamento import Armazenamento
from ..certificado import Certificado
from ..config import Config
from ..erros import ErroNotaXML


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Tarefa:
    id: int
    nome: str
    inicio: datetime = field(default_factory=_agora)
    fim: datetime | None = None
    situacao: str = "executando"  # executando, concluida, erro
    linhas: list[str] = field(default_factory=list)
    thread: threading.Thread | None = field(default=None, repr=False)

    def log(self, linha: str):
        self.linhas.append(linha)

    @property
    def recente(self) -> bool:
        """Em andamento ou terminada há menos de 2 minutos (o painel mostra o log aberto)."""
        return self.fim is None or (_agora() - self.fim).total_seconds() < 120

    def como_dict(self) -> dict:
        return {
            "id": self.id,
            "nome": self.nome,
            "situacao": self.situacao,
            "inicio": self.inicio.isoformat(),
            "fim": self.fim.isoformat() if self.fim else None,
            "linhas": self.linhas,
        }


class GerenciadorTarefas:
    def __init__(self, cfg: Config, abrir_sessao=operacoes.abrir_sincronizador):
        self.cfg = cfg
        self._abrir_sessao = abrir_sessao
        self._trava = threading.Lock()
        self._contador = 0
        self.atual: Tarefa | None = None
        self.historico: deque[Tarefa] = deque(maxlen=20)
        self.certificado: Certificado | None = None
        self.erro_certificado: str | None = None
        self._parar = threading.Event()
        self._agendador: threading.Thread | None = None
        self._ultima_automatica: datetime | None = None
        if cfg.senha is not None:
            try:
                self.desbloquear(cfg.senha)
            except ErroNotaXML as exc:
                self.erro_certificado = str(exc)

    # ---- certificado ----------------------------------------------------

    def desbloquear(self, senha: str) -> Certificado:
        cert = Certificado.carregar(self.cfg.certificado, senha)
        if cert.vencido:
            raise ErroNotaXML(f"O certificado venceu em {cert.valido_ate:%d/%m/%Y}.")
        self.certificado = cert
        self.erro_certificado = None
        return cert

    # ---- execução ---------------------------------------------------------

    @property
    def ocupado(self) -> bool:
        return self.atual is not None and self.atual.situacao == "executando"

    def ultima(self) -> Tarefa | None:
        return self.atual or (self.historico[0] if self.historico else None)

    def iniciar(self, nome: str, funcao: Callable, *args, **kwargs) -> Tarefa:
        """Executa `funcao(sincronizador, log, *args, **kwargs)` numa thread. Erro se já houver tarefa rodando."""
        if self.certificado is None:
            raise ErroNotaXML("Desbloqueie o certificado digital antes de acessar a SEFAZ.")
        with self._trava:
            if self.ocupado:
                raise ErroNotaXML(f"Aguarde: '{self.atual.nome}' ainda está em andamento.")
            self._contador += 1
            if self.atual is not None:
                self.historico.appendleft(self.atual)
            tarefa = self.atual = Tarefa(self._contador, nome)
        thread = threading.Thread(target=self._executar, args=(tarefa, funcao, args, kwargs), daemon=True)
        thread.start()
        tarefa.thread = thread
        return tarefa

    def _executar(self, tarefa: Tarefa, funcao: Callable, args, kwargs):
        try:
            with self._abrir_sessao(self.cfg, self.certificado, tarefa.log) as sinc:
                funcao(sinc, tarefa.log, *args, **kwargs)
            tarefa.situacao = "concluida"
        except (ErroNotaXML, ValueError) as exc:
            tarefa.log(f"Erro: {exc}")
            tarefa.situacao = "erro"
        except Exception:  # noqa: BLE001 - a thread não pode morrer calada
            tarefa.log("Erro inesperado:\n" + traceback.format_exc())
            tarefa.situacao = "erro"
        finally:
            tarefa.fim = _agora()

    # ---- agendamento ------------------------------------------------------

    def proxima_sincronizacao(self) -> datetime | None:
        banco = Armazenamento(self.cfg.pasta_dados)
        try:
            return banco.estado(self.cfg.documento, self.cfg.ambiente).proxima_consulta
        finally:
            banco.fechar()

    def _sincronizacao_devida(self) -> bool:
        if self.certificado is None or self.ocupado:
            return False
        proxima = self.proxima_sincronizacao()
        if proxima is not None and proxima > _agora():
            return False
        intervalo = self.cfg.web.intervalo_minutos * 60
        return self._ultima_automatica is None or (_agora() - self._ultima_automatica).total_seconds() >= intervalo

    def verificar_agenda(self) -> Tarefa | None:
        if not self._sincronizacao_devida():
            return None
        try:
            tarefa = self.iniciar("Sincronização automática", operacoes.sincronizar,
                                  ciencia=self.cfg.ciencia_automatica)
        except ErroNotaXML:
            return None
        self._ultima_automatica = _agora()
        return tarefa

    def iniciar_agendador(self, intervalo_verificacao: int = 60):
        def laco():
            while not self._parar.wait(intervalo_verificacao):
                self.verificar_agenda()

        self._agendador = threading.Thread(target=laco, daemon=True, name="agendador-notaxml")
        self._agendador.start()

    def parar(self):
        self._parar.set()
