# notaxml — download de NF-e direto da SEFAZ

Baixa automaticamente os XMLs das **NF-e emitidas contra a sua empresa** (compras, notas em que ela é
destinatária, transportadora ou autorizada no XML) usando o web service oficial **NFeDistribuicaoDFe**
do Ambiente Nacional da SEFAZ, autenticado com o **certificado digital A1** da empresa.

Também envia a **Manifestação do Destinatário** (Ciência, Confirmação, Desconhecimento e Operação não
Realizada), que é o que libera o XML completo de cada nota.

## Jeito mais fácil: NotaXML.exe (Windows)

1. Baixe o `NotaXML.exe` (veja abaixo onde encontrar).
2. Dê dois cliques. Abre uma janela preta (deixe-a aberta — é o sistema rodando) e o navegador
   com a tela de boas-vindas.
3. Escolha o certificado A1 (`.pfx`), digite a senha, a UF e clique em **Salvar**. Pronto.

- Não precisa instalar Python nem nada mais.
- A configuração e uma cópia do certificado ficam em `%LOCALAPPDATA%\NotaXML`; os XMLs baixados ficam
  em **Documentos\NotaXML** (há um botão "Abrir pasta dos XMLs" na tela).
- Marcando "Lembrar a senha", ela é guardada criptografada pelo Windows, só para o seu usuário.
- Para encerrar, feche a janela preta. Abrir o `.exe` de novo com o sistema já aberto só abre o navegador.
- **Modo portátil** (pendrive/pasta de rede): coloque um `config.toml` ao lado do `.exe` e tudo fica nessa pasta.
- Para abrir junto com o Windows: tecla `Win+R` → `shell:startup` → cole ali um atalho do `NotaXML.exe`.

**Aviso do Windows na primeira vez:** como o executável não é assinado digitalmente, o SmartScreen pode
mostrar "O Windows protegeu o computador". Clique em **Mais informações → Executar assim mesmo**.

### Onde baixar o .exe

O GitHub gera o executável automaticamente a cada atualização do código (aba **Actions** do repositório →
execução mais recente de "Gerar NotaXML.exe" → seção *Artifacts* → `NotaXML-windows`). Ao criar uma tag
`v1.0.0`, o `.exe` também é publicado na página **Releases**.

Para gerar no próprio computador Windows (com Python 3.11+ instalado): `empacotamento\construir.bat`.

## Como funciona

1. A SEFAZ numera cada documento disponível para o seu CNPJ com um **NSU** sequencial.
2. O comando `sincronizar` pede tudo a partir do último NSU salvo, até alcançar o `maxNSU`,
   e grava cada documento recebido:
   - `procNFe` → XML completo da nota (`dados/xml/nfe/AAAA-MM/<chave>-nfe.xml`)
   - `resNFe` → **resumo** de uma nota que ainda não foi manifestada (`dados/xml/resumos/`)
   - `procEventoNFe` / `resEvento` → eventos: cancelamentos, cartas de correção etc. (`dados/xml/eventos/`)
3. Para notas que chegaram só como resumo, envie a **Ciência da Operação**. Depois disso o XML completo
   passa a vir nas próximas sincronizações (ou pode ser pedido na hora com `baixar`).
4. Um índice SQLite (`dados/notas.db`) guarda o último NSU e a situação de cada nota.

> A SEFAZ só disponibiliza documentos dos **últimos 90 dias** e exige **1 hora de intervalo** depois que
> a consulta não encontra nada novo. Desrespeitar isso causa bloqueio temporário (rejeição 656 –
> consumo indevido). O sistema controla esse intervalo sozinho.

## Instalação

Requer Python 3.11 ou superior.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

## Configuração

1. Copie `config.exemplo.toml` para `config.toml` e preencha o CNPJ e a UF da empresa.
2. Coloque o certificado A1 (`.pfx`/`.p12`) na pasta e informe o caminho em `[certificado] arquivo`.
3. Informe a senha do certificado pela variável de ambiente `NFE_CERT_SENHA` (ou deixe em branco
   para digitá-la a cada execução).

```bash
export NFE_CERT_SENHA='senha-do-certificado'   # Windows (PowerShell): $env:NFE_CERT_SENHA='...'
notaxml certificado                              # confere se o certificado abre e o CNPJ
```

`config.toml`, certificados e a pasta `dados/` estão no `.gitignore` — nunca envie isso ao GitHub.

## Interface no navegador

```bash
notaxml web
```

Abre o navegador em <http://127.0.0.1:8000> com:

- **Lista de notas** com totais, busca por emitente/CNPJ/chave, filtro por período, situação e pendências;
- **Sincronizar agora** (com opção de dar ciência nas notas novas) e um painel que mostra o andamento ao vivo;
- **Manifestação em lote**: marque as notas, escolha o evento e clique em *Manifestar*;
- **Download** do XML de cada nota, de um **ZIP** com as selecionadas/filtradas e exportação **CSV**;
- Página de cada nota com dados, eventos (cancelamento, carta de correção...) e seus XMLs;
- **Sincronização automática** de hora em hora enquanto o sistema estiver aberto (`[web] sincronizacao_automatica`).

Se a senha do certificado não estiver em `NFE_CERT_SENHA`, a tela *Certificado* pede a senha
(ela fica só na memória enquanto o sistema estiver aberto).

**Acesso por outros computadores da rede:** use `host = "0.0.0.0"` em `[web]` e defina uma senha de acesso
(`NOTAXML_WEB_SENHA` ou `[web] senha`) — sem senha o sistema se recusa a abrir para a rede, porque a
interface consegue enviar eventos assinados com o certificado da empresa. Não exponha na internet.

Para deixar sempre ligado, configure `notaxml web --sem-navegador` como serviço (systemd no Linux,
ou uma tarefa "Ao iniciar o computador" no Agendador de Tarefas do Windows).

## Linha de comando

Tudo o que a interface faz também existe na linha de comando:

```bash
# Baixa tudo o que houver de novo
notaxml sincronizar

# Baixa e já dá Ciência da Operação nas notas que vieram só como resumo
notaxml sincronizar --ciencia-automatica

# Manifestação manual (uma ou várias chaves)
notaxml manifestar 3526...0001 --evento ciencia
notaxml manifestar 3526...0001 --evento confirmacao
notaxml manifestar 3526...0001 --evento desconhecimento
notaxml manifestar 3526...0001 --evento nao-realizada -j "Mercadoria não foi entregue"

# Pede o XML de notas específicas pela chave (ou todas as manifestadas que ainda não têm XML)
notaxml baixar 3526...0001
notaxml baixar

# Consulta o que já foi baixado
notaxml listar
notaxml listar --pendentes
notaxml listar --csv notas.csv                   # abre direto no Excel
```

### Rodar automaticamente sem a interface

Agende `notaxml sincronizar --ciencia-automatica` para rodar **de hora em hora** (ou com intervalo maior):

- **Linux (cron):** `0 * * * * cd /caminho/do/projeto && NFE_CERT_SENHA=... .venv/bin/notaxml sincronizar --ciencia-automatica >> sync.log 2>&1`
- **Windows:** Agendador de Tarefas, executando `.venv\Scripts\notaxml.exe sincronizar --ciencia-automatica`
  com "Iniciar em" apontando para a pasta do projeto.

## Sobre a Manifestação do Destinatário

| Evento | Quando usar | Prazo* |
|---|---|---|
| Ciência da Operação | Você sabe que a nota existe mas ainda não conferiu. Libera o XML. | 10 dias |
| Confirmação da Operação | A operação ocorreu e a mercadoria foi recebida. | 180 dias |
| Desconhecimento da Operação | A empresa não reconhece essa compra. | 180 dias |
| Operação não Realizada | A operação foi combinada mas não aconteceu (exige justificativa). | 180 dias |

\* contados da autorização da NF-e. A Ciência é provisória: a empresa ainda deve enviar uma
manifestação conclusiva (Confirmação, Desconhecimento ou Não Realizada) — combine isso com o seu contador.

## Problemas comuns

- **`Falha de SSL ... verificação do servidor`**: o servidor da SEFAZ usa certificado da ICP-Brasil, que
  pode não estar na lista de autoridades do Python. Baixe as cadeias da ICP-Brasil no site do ITI
  (<https://www.gov.br/iti/pt-br/assuntos/repositorio>), junte os certificados (`.crt` em formato PEM)
  num único arquivo e aponte `ca_bundle` para ele em `[sefaz]`.
- **656 – Consumo indevido**: houve consultas demais. Aguarde 1 hora; o sistema já registra esse bloqueio.
- **Nota aparece só com resumo**: faça a Ciência da Operação (`manifestar` ou `--ciencia-automatica`).
- **Notas de mais de 90 dias**: não estão mais disponíveis na distribuição; peça o XML ao fornecedor.

## Testes

```bash
pip install -e '.[dev]'
pytest
```

Os testes não acessam a SEFAZ: usam um certificado autoassinado gerado na hora e respostas simuladas.
Se o `xmlsec1` estiver instalado, a assinatura da manifestação também é validada por ele.

## Estrutura

| Módulo | Responsabilidade |
|---|---|
| `notaxml/certificado.py` | Leitura do certificado A1 (.pfx) |
| `notaxml/soap.py` | Cliente SOAP 1.2 com TLS mútuo |
| `notaxml/distribuicao.py` | NFeDistribuicaoDFe (consulta por NSU e por chave) |
| `notaxml/manifestacao.py` + `assinatura.py` | Eventos de manifestação assinados (XMLDSig) |
| `notaxml/armazenamento.py` | XMLs em disco + índice SQLite |
| `notaxml/sincronizador.py` | Regras de NSU, intervalo de 1 hora e bloqueio 656 |
| `notaxml/operacoes.py` | Operações compartilhadas pela CLI e pela web |
| `notaxml/cli.py` | Linha de comando |
| `notaxml/web/` | Interface web (Flask): rotas, tarefas em segundo plano, templates e estilos |
