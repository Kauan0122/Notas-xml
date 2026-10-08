import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .erros import ErroConfiguracao
from .ufs import CODIGOS_UF

AMBIENTES = {"producao": 1, "homologacao": 2}


@dataclass
class ConfigWeb:
    host: str = "127.0.0.1"
    porta: int = 8000
    senha: str | None = None  # senha de acesso à interface (obrigatória fora do localhost)
    sincronizacao_automatica: bool = False
    intervalo_minutos: int = 60


@dataclass
class Config:
    documento: str  # CNPJ (ou CPF) da empresa interessada
    uf: str
    certificado: Path
    senha: str | None
    ambiente: int
    verificar_ssl: bool | str
    timeout: int
    pasta_dados: Path
    ciencia_automatica: bool
    web: ConfigWeb = field(default_factory=ConfigWeb)

    @property
    def cuf(self) -> int:
        return CODIGOS_UF[self.uf]


def _caminho(base: Path, valor: str) -> Path:
    caminho = Path(valor).expanduser()
    return caminho if caminho.is_absolute() else base / caminho


def carregar_config(caminho: str | Path) -> Config:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroConfiguracao(
            f"Arquivo de configuração não encontrado: {caminho}. Copie config.exemplo.toml para config.toml e preencha."
        )
    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ErroConfiguracao(f"Erro de sintaxe em {caminho}: {exc}") from exc
    base = caminho.parent

    empresa = dados.get("empresa", {})
    documento = re.sub(r"\D", "", str(empresa.get("cnpj", "")))
    if len(documento) not in (11, 14):
        raise ErroConfiguracao("Informe o CNPJ da empresa (14 dígitos) em [empresa] cnpj.")
    uf = str(empresa.get("uf", "")).upper()
    if uf not in CODIGOS_UF:
        raise ErroConfiguracao("Informe a UF da empresa (ex.: \"SP\") em [empresa] uf.")

    cert = dados.get("certificado", {})
    if not cert.get("arquivo"):
        raise ErroConfiguracao("Informe o caminho do certificado A1 (.pfx) em [certificado] arquivo.")
    senha = os.environ.get("NFE_CERT_SENHA") or cert.get("senha") or None

    sefaz = dados.get("sefaz", {})
    nome_ambiente = str(sefaz.get("ambiente", "producao")).lower()
    if nome_ambiente not in AMBIENTES:
        raise ErroConfiguracao("[sefaz] ambiente deve ser \"producao\" ou \"homologacao\".")
    verificar_ssl: bool | str = bool(sefaz.get("verificar_ssl", True))
    if verificar_ssl and sefaz.get("ca_bundle"):
        verificar_ssl = str(_caminho(base, sefaz["ca_bundle"]))

    return Config(
        documento=documento,
        uf=uf,
        certificado=_caminho(base, cert["arquivo"]),
        senha=senha,
        ambiente=AMBIENTES[nome_ambiente],
        verificar_ssl=verificar_ssl,
        timeout=int(sefaz.get("timeout", 60)),
        pasta_dados=_caminho(base, dados.get("armazenamento", {}).get("pasta", "dados")),
        ciencia_automatica=bool(dados.get("sincronizacao", {}).get("ciencia_automatica", False)),
        web=_config_web(dados.get("web", {})),
    )


def _config_web(web: dict) -> ConfigWeb:
    intervalo = int(web.get("intervalo_minutos", 60))
    if intervalo < 60:
        raise ErroConfiguracao("[web] intervalo_minutos deve ser de pelo menos 60 (regra da SEFAZ).")
    return ConfigWeb(
        host=str(web.get("host", "127.0.0.1")),
        porta=int(web.get("porta", 8000)),
        senha=os.environ.get("NOTAXML_WEB_SENHA") or web.get("senha") or None,
        sincronizacao_automatica=bool(web.get("sincronizacao_automatica", False)),
        intervalo_minutos=intervalo,
    )
