import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import segredo
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
    https: bool = False  # o acesso é por HTTPS (marca o cookie de sessão como "Secure")
    atras_de_proxy: bool = False  # há um proxy reverso (Caddy, nginx...) na frente: confia no X-Forwarded-*


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


def segredo_do_ambiente(nome: str) -> str | None:
    """Valor de uma variável de ambiente ou, no padrão dos Docker secrets, do arquivo apontado por NOME_FILE."""
    valor = os.environ.get(nome)
    if valor:
        return valor
    arquivo = os.environ.get(f"{nome}_FILE")
    if arquivo:
        try:
            return Path(arquivo).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise ErroConfiguracao(f"Não foi possível ler {nome}_FILE ({arquivo}): {exc}") from exc
    return None


def _booleano_do_ambiente(nome: str, padrao: bool) -> bool:
    valor = os.environ.get(nome)
    return padrao if valor is None else valor.strip().lower() in ("1", "true", "sim", "yes", "on")


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
    senha = _revelar(segredo_do_ambiente("NFE_CERT_SENHA") or cert.get("senha") or None)

    sefaz = dados.get("sefaz", {})
    nome_ambiente = str(sefaz.get("ambiente", "producao")).lower()
    if nome_ambiente not in AMBIENTES:
        raise ErroConfiguracao("[sefaz] ambiente deve ser \"producao\" ou \"homologacao\".")
    verificar_ssl: bool | str = bool(sefaz.get("verificar_ssl", True))
    ca_bundle = os.environ.get("NOTAXML_CA_BUNDLE") or sefaz.get("ca_bundle")
    if verificar_ssl and ca_bundle:
        verificar_ssl = str(_caminho(base, ca_bundle))
        if not Path(verificar_ssl).is_file():
            raise ErroConfiguracao(f"Cadeia de certificados (ca_bundle) não encontrada: {verificar_ssl}")

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


def _revelar(senha: str | None) -> str | None:
    """Senhas guardadas pelo cofre do Windows (prefixo "dpapi:") voltam ao texto original."""
    if senha and senha.startswith(segredo.PREFIXO):
        try:
            return segredo.revelar(senha)
        except (OSError, RuntimeError, ValueError):
            return None  # guardada por outro usuário/computador: o sistema pede de novo
    return senha


def _config_web(web: dict) -> ConfigWeb:
    intervalo = int(web.get("intervalo_minutos", 60))
    if intervalo < 60:
        raise ErroConfiguracao("[web] intervalo_minutos deve ser de pelo menos 60 (regra da SEFAZ).")
    return ConfigWeb(
        host=str(web.get("host", "127.0.0.1")),
        porta=int(web.get("porta", 8000)),
        senha=_revelar(segredo_do_ambiente("NOTAXML_WEB_SENHA") or web.get("senha") or None),
        sincronizacao_automatica=bool(web.get("sincronizacao_automatica", False)),
        intervalo_minutos=intervalo,
        https=_booleano_do_ambiente("NOTAXML_HTTPS", bool(web.get("https", False))),
        atras_de_proxy=_booleano_do_ambiente("NOTAXML_PROXY", bool(web.get("atras_de_proxy", False))),
    )


def ler_config_web(caminho: str | Path) -> ConfigWeb:
    """Opções do servidor web mesmo sem uma configuração completa (primeiro uso ou arquivo com problemas).

    Variáveis de ambiente (NOTAXML_WEB_SENHA, NOTAXML_HTTPS, NOTAXML_PROXY) valem em qualquer situação.
    """
    web = ler_secoes(caminho).get("web", {})
    try:
        return _config_web(web)
    except (ErroConfiguracao, ValueError, TypeError):
        return _config_web({"senha": web.get("senha")})


def _toml(valor) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int):
        return str(valor)
    return json.dumps(str(valor), ensure_ascii=False)  # escapes JSON são válidos em TOML


def salvar_config(caminho: str | Path, secoes: dict[str, dict]):
    """Grava o config.toml (usado pela tela de configuração). Valores None são omitidos."""
    linhas = ["# Gerado pela tela de configuração do NotaXML.", ""]
    for secao, valores in secoes.items():
        linhas.append(f"[{secao}]")
        linhas += [f"{chave} = {_toml(valor)}" for chave, valor in valores.items() if valor is not None]
        linhas.append("")
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text("\n".join(linhas), encoding="utf-8")
    temporario.replace(caminho)


def ler_secoes(caminho: str | Path) -> dict:
    """Conteúdo bruto do config.toml (vazio se não existir ou estiver corrompido)."""
    caminho = Path(caminho)
    try:
        return tomllib.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
