"""
Robo de leitura/preenchimento de NFSe - WS360 (Ford/KPMG)
============================================================

O robo executa o fluxo completo para um ID especifico (ID_TESTE,
configuravel abaixo):
1. Conecta em um navegador Chrome ja aberto e logado por voce (via CDP)
2. Navega: Minhas Tarefas > Gestao de Entradas
3. Pesquisa pelo ID do processo e abre o modal (lapis ou olho, se ja foi
   aberto antes)
4. Vai na aba "Anexos" e procura um arquivo XML
5. Se NAO houver XML, ou faltar algum campo obrigatorio no XML: pula o ID
   e informa que precisa de revisao manual (nao mexe em nada na tela)
6. Se houver XML e os campos obrigatorios estiverem completos: extrai os
   dados (padrao NFSe Nacional), preenche a aba "Capa do DFe" (sem
   sobrescrever campos que o sistema ja preencheu sozinho), clica em
   "Confirmar e Gravar Dados" e aguarda a gravacao terminar
7. Encaminha a tarefa: abre o dropdown "Encaminhar" e clica em
   "Encaminhar p/ Consultas Cadastrais" (aceitando o confirm() nativo do
   navegador que essa acao dispara)

Requisitos:
    pip install playwright
    playwright install chromium

Como rodar:
    1. Abra o Chrome com a porta de depuracao habilitada (veja CDP_URL
       mais abaixo) e faca login manualmente no sistema
    2. Deixe a aba aberta na tela inicial (Workspace)
    3. Rode: python robo_nfse.py

IMPORTANTE - Ajustes necessarios antes de rodar:
    - Todos os seletores de navegacao (menu, campo de pesquisa, icone de
      lapis, deteccao de XML nos anexos) sao uma estimativa a partir dos
      prints enviados - va testando e ajustando conforme os erros
      aparecerem (marcados com comentario AJUSTAR no codigo)
"""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path

from playwright.sync_api import sync_playwright, Page

# ---------------------------------------------------------------------------
# CONFIGURACAO - ajuste aqui
# ---------------------------------------------------------------------------

# O robo NAO faz login. Ele se conecta a um navegador Chrome que voce ja
# abriu e ja logou manualmente, via CDP (Chrome DevTools Protocol).
#
# Para isso, feche todas as janelas do Chrome e abra ele assim (Windows,

#
#   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
#
# ou no atalho do Chrome, adicione --remote-debugging-port=9222 no final do
# campo "Destino". Depois, faca login normalmente no sistema nessa janela
# e deixe ela aberta na tela do DFe que deseja preencher antes de rodar o robo.
CDP_URL = os.getenv("NFSE_CDP_URL", "http://localhost:9222")

# ETAPA ATUAL DO PROJETO: apenas validar a extracao do XML para um ID
# especifico, sem preencher nada na tela ainda. Troque aqui o ID que quer
# testar (ou passe por variavel de ambiente).
ID_TESTE = os.getenv("NFSE_ID_TESTE", "1434873")

# Campos que o robo considera obrigatorios: se algum desses vier vazio
# tanto na tela quanto no XML, o ID e pulado para revisao manual.
CAMPOS_OBRIGATORIOS = ["cnpj_prestador", "nome_prestador", "codigo_servico"]

# Pasta temporaria onde o XML baixado da aba "Anexos" sera salvo
PASTA_DOWNLOAD = Path("./downloads")
PASTA_DOWNLOAD.mkdir(exist_ok=True)

# Tabela minima de codigo IBGE do estado (2 primeiros digitos do cMun) -> UF
# usada para descobrir a UF do Tomador quando o XML so traz o codigo da cidade
UF_POR_CODIGO_ESTADO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}

# ---------------------------------------------------------------------------
# 1) EXTRACAO DOS DADOS DO XML
# ---------------------------------------------------------------------------

NS = {"nfse": "http://www.sped.fazenda.gov.br/nfse"}


@dataclass
class DadosNFSe:
    numero_nota: str = ""
    serie: str = ""
    cnpj_prestador: str = ""
    nome_prestador: str = ""
    cidade_prestador: str = ""
    uf_prestador: str = ""
    cnpj_tomador: str = ""
    nome_tomador: str = ""
    # cidade_tomador/uf_tomador sao extraidos so para conferencia/log:
    # o sistema preenche esses dois campos sozinho assim que o robo
    # seleciona o CNPJ Tomador na tela, entao o robo NAO digita neles.
    cidade_tomador_xml: str = ""
    uf_tomador_xml: str = ""
    valor_nota: str = ""
    valor_servico: str = ""
    codigo_verificacao: str = ""
    data_emissao: str = ""
    data_vencimento: str = ""
    data_pagamento: str = ""
    codigo_servico: str = ""
    lc116: str = ""
    descricao_lc116: str = ""


def _text(root, path, default=""):
    el = root.find(path, NS)
    return el.text.strip() if el is not None and el.text else default


def _formata_data(dh_iso: str) -> str:
    """2026-07-10T10:38:00-03:00 -> 10/07/2026"""
    if not dh_iso:
        return ""
    data = dh_iso.split("T")[0]
    ano, mes, dia = data.split("-")
    return f"{dia}/{mes}/{ano}"


def _formata_valor(valor: str) -> str:
    """350.00 -> 350,00"""
    if not valor:
        return "0,00"
    return f"{float(valor):.2f}".replace(".", ",")


def _cTribNac_para_lc116(cod: str) -> str:
    """140101 -> 14.01 (item.subitem da lista LC 116/2003)"""
    if not cod or len(cod) < 4:
        return ""
    return f"{cod[0:2]}.{cod[2:4]}"


def extrair_dados_nfse(caminho_xml: str) -> DadosNFSe:
    tree = ET.parse(caminho_xml)
    root = tree.getroot()

    inf = root.find("nfse:infNFSe", NS)
    dps_inf = inf.find("nfse:DPS/nfse:infDPS", NS)

    dados = DadosNFSe()

    # Numero / serie
    dados.numero_nota = _text(inf, "nfse:nNFSe")
    dados.serie = _text(dps_inf, "nfse:serie")

    # Prestador
    emit = inf.find("nfse:emit", NS)
    dados.cnpj_prestador = _text(emit, "nfse:CNPJ")
    dados.nome_prestador = _text(emit, "nfse:xNome")
    dados.uf_prestador = _text(emit, "nfse:enderNac/nfse:UF")
    dados.cidade_prestador = _text(inf, "nfse:xLocPrestacao")

    # Tomador - o robo so precisa do CNPJ; cidade/UF sao preenchidos pelo
    # proprio sistema ao selecionar o CNPJ Tomador na tela. Os campos abaixo
    # sao extraidos apenas para conferencia (comparar com o que o sistema
    # trouxe automaticamente).
    toma = dps_inf.find("nfse:toma", NS)
    dados.cnpj_tomador = _text(toma, "nfse:CNPJ")
    dados.nome_tomador = _text(toma, "nfse:xNome")
    cmun_tomador = _text(toma, "nfse:end/nfse:endNac/nfse:cMun")
    dados.uf_tomador_xml = UF_POR_CODIGO_ESTADO.get(cmun_tomador[:2], "")
    dados.cidade_tomador_xml = cmun_tomador

    # Valores
    valores_topo = inf.find("nfse:valores", NS)
    dados.valor_nota = _formata_valor(_text(valores_topo, "nfse:vLiq"))
    valor_servico = _text(dps_inf, "nfse:valores/nfse:vServPrest/nfse:vServ")
    dados.valor_servico = _formata_valor(valor_servico)

    # Datas
    dados.data_emissao = _formata_data(_text(dps_inf, "nfse:dhEmi"))
    # Nao existem no XML - preencher conforme regra de negocio da empresa
    dados.data_vencimento = ""
    dados.data_pagamento = ""

    # Codigo de verificacao - nao existe no padrao NFSe Nacional.
    # Se o seu sistema usa outro identificador (ex: Id do infNFSe), ajuste aqui:
    dados.codigo_verificacao = ""

    # Servico / LC 116
    cod_serv = dps_inf.find("nfse:serv/nfse:cServ/nfse:cTribNac", NS)
    dados.codigo_servico = cod_serv.text.strip() if cod_serv is not None else ""
    dados.lc116 = _cTribNac_para_lc116(dados.codigo_servico)
    desc = _text(inf, "nfse:xTribNac")
    dados.descricao_lc116 = desc

    return dados


# ---------------------------------------------------------------------------
# 2) SELETORES DO FORMULARIO - AJUSTAR CONFORME O HTML REAL DO SISTEMA
# ---------------------------------------------------------------------------
# Estrategia: localizar o input mais proximo do texto do label. Isso e mais
# resiliente a mudancas de id/name do que usar seletores fixos, mas se o
# sistema usar uma estrutura muito diferente, troque por seletores CSS
# diretos (ex: page.locator("#numeroNota")).

def _campo_esta_vazio(valor_atual: str) -> bool:
    """
    Considera vazio tanto string em branco quanto valores numericos
    zerados (ex: "0", "0,00", "0.00") - o sistema pode trazer um
    "0,00" de fabrica em campos de valor que na pratica ainda nao
    foram preenchidos.
    """
    valor_atual = (valor_atual or "").strip()
    if not valor_atual:
        return True
    try:
        return float(valor_atual.replace(",", ".")) == 0
    except ValueError:
        return False


def preencher_por_label(page: Page, texto_label: str, valor: str, indice: int = 0):
    """
    Encontra o input que vem logo apos um texto de label na tela e
    preenche - MAS somente se o campo estiver vazio (ou zerado, ex:
    "0,00"). Se o sistema ja trouxe algum valor real sozinho
    (preenchimento automatico), o robo NAO sobrescreve.
    """
    if not valor:
        return
    locator = page.locator(
        f"xpath=//*[contains(normalize-space(text()), '{texto_label}')]"
        f"/following::input[1]"
    ).nth(indice)
    valor_atual = (locator.input_value() or "").strip()
    if not _campo_esta_vazio(valor_atual):
        print(f"  (mantido) '{texto_label}' ja estava preenchido: {valor_atual}")
        return
    locator.fill(str(valor))
    print(f"  (preenchido) '{texto_label}' = {valor}")


def selecionar_cnpj_tomador(page: Page, cnpj: str):
    """
    Seleciona o CNPJ Tomador no campo real da tela: um <select id="dest_cnpj">
    nativo (nao um combo customizado). Ele tem
    onchange="BuscaDadosEmitDest(...)", que e o gatilho que faz o sistema
    preencher Cidade/UF do Tomador automaticamente - por isso o robo NAO
    digita nesses dois campos.
    """
    if not cnpj:
        return
    # ATENCAO: a pagina tem DOIS elementos com id="dest_cnpj" (um <select>
    # real e um <input readonly> que so exibe o valor visualmente) - por
    # isso apontamos pela tag "select" especificamente, para nao dar erro
    # de ambiguidade.
    select_tomador = page.locator('select[name="dest_cnpj"]')

    # Procura, entre as opcoes do select, a que contem o CNPJ (o texto da
    # opcao normalmente vem como "03470727000473 - FORD MOTOR COMPANY...").
    # Fazemos isso via JS para nao depender do formato exato do value.
    valor_opcao = select_tomador.evaluate(
        """(select, cnpj) => {
            const opcao = Array.from(select.options).find(
                o => o.value.includes(cnpj) || o.textContent.includes(cnpj)
            );
            return opcao ? opcao.value : null;
        }""",
        cnpj,
    )
    if not valor_opcao:
        print(f"  [ATENÇÃO] CNPJ Tomador {cnpj} não encontrado nas opções do campo dest_cnpj.")
        return

    # Usamos JS direto (em vez de select_option) porque o <select> pode
    # estar visualmente escondido (substituido por um componente
    # customizado, dado o <input readonly> "gemeo" que vimos no HTML) -
    # select_option exige visibilidade e travaria nesse caso. Definir o
    # valor + disparar "change" manualmente aciona o
    # onchange="BuscaDadosEmitDest(...)" da mesma forma.
    select_tomador.evaluate(
        """(select, valor) => {
            select.value = valor;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        valor_opcao,
    )
    page.wait_for_timeout(800)  # aguarda o sistema popular Cidade/UF do Tomador


# ---------------------------------------------------------------------------
# 3) FLUXO PRINCIPAL DE AUTOMACAO
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 3) NAVEGACAO ATE O PROCESSO (Minhas Tarefas > Gestao de Entradas > ID)
# ---------------------------------------------------------------------------

def abrir_processo_por_id(page: Page, id_processo: str):
    """
    Replica o fluxo manual:
    Minhas Tarefas > Gestao de Entradas > pesquisa pelo ID > clica no lapis
    > abre o modal do processo.

    AJUSTAR: todos os seletores abaixo sao uma estimativa a partir dos
    prints - confira no navegador (Inspecionar elemento) e troque se
    necessario.
    """
    page.get_by_text("Minhas Tarefas", exact=False).first.click()
    page.wait_for_timeout(300)
    page.get_by_text("Gestão de Entradas", exact=False).first.click()
    page.wait_for_load_state("networkidle")

    # Campo "Pesquisar" - identificado pelo atributo aria-controls do
    # DataTable (confirmado no HTML real da pagina). Usamos .type() em vez
    # de .fill() porque o DataTables normalmente dispara a busca no evento
    # keyup, e .fill() nem sempre gera esse evento corretamente.
    campo_pesquisa = page.locator('input[aria-controls="DataTable_Process001"]')
    campo_pesquisa.click()
    campo_pesquisa.fill("")  # limpa qualquer busca anterior
    campo_pesquisa.type(str(id_processo), delay=50)

    # Aguarda a chamada AJAX da busca (server-side) terminar, em vez de um
    # tempo fixo - tabelas grandes podem demorar mais que 1 segundo.
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    # Botao de abrir o processo: pode aparecer como "lapis" (tarefa ainda
    # nao aberta, onclick="fetch_accept(<id>,<modelo>)") ou como "olho"
    # (tarefa ja aberta/travada por este usuario antes, onclick=
    # "fetch_select(<id>,<modelo>)"). Os dois usam data-target="#modal_tarefa"
    # e o mesmo padrao de argumento (id, modelo), entao localizamos por isso
    # em vez de depender do nome exato da funcao JS.
    botao_editar = page.locator(
        f'button[data-target="#modal_tarefa"][onclick*="({id_processo},"]'
    ).first
    try:
        botao_editar.click(timeout=15000)
    except Exception:
        caminho_print = PASTA_DOWNLOAD / f"debug_busca_id_{id_processo}.png"
        page.screenshot(path=str(caminho_print), full_page=True)
        print(
            f"[ERRO] Nao encontrei o botao de abrir o ID {id_processo} apos "
            f"a busca. Print salvo em: {caminho_print}"
        )
        raise

    # O botao dispara data-target="#modal_tarefa" + uma chamada AJAX
    # (fetch_accept ou fetch_select) que carrega o conteudo do processo
    # dentro do modal. Esperamos o modal abrir e so depois checamos o
    # conteudo dentro dele.
    page.wait_for_selector("#modal_tarefa", state="visible", timeout=10000)
    page.wait_for_selector("text=Processo Gestão de Entradas", timeout=10000)

    # Garante que a aba com os campos de lancamento (Capa do DFe) esta ativa
    page.get_by_role("link", name="Capa do DFe").click()


def procurar_xml_nos_anexos(page: Page):
    """
    Vai na aba Anexos, procura a linha cujo "Nome Documento" termina em
    .xml e baixa o arquivo. Retorna o caminho local do arquivo baixado,
    ou None se nao houver nenhum XML na lista de anexos (nesse caso o ID
    deve ser pulado, conforme combinado).

    IMPORTANTE: em vez de clicar no botao de download (que abre uma nova
    aba via <form target="_blank">), replicamos a MESMA requisicao HTTP
    que esse formulario faria, usando os cookies da sessao atual. Isso e
    necessario porque o robo se conecta a um navegador JA aberto (via
    CDP) - nesse cenario o Playwright nao consegue interceptar de forma
    confiavel o evento de download disparado numa aba nova, entao o
    arquivo acaba baixando "escondido" na pasta de Downloads padrao do
    Windows, sem o robo saber o caminho exato.
    """
    page.get_by_role("link", name="Anexos").click()
    page.wait_for_selector("text=Lista de Anexos do Processo", timeout=10000)

    # Localiza a linha cujo Nome Documento termina em .xml (case-insensitive)
    linha_xml = page.locator(
        "xpath=//table[.//th[contains(normalize-space(.), 'Nome Documento')]]"
        "/tbody/tr[td[contains("
        "translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '.xml'"
        ")]]"
    )
    if linha_xml.count() == 0:
        return None

    nome_arquivo = linha_xml.first.locator("td").nth(1).inner_text().strip()

    # O formulario de download fica dentro da celula de Acao dessa linha:
    # <form action="ws360_downdoc.php" method="post" target="_blank">
    #   <input type="hidden" name="iddoc" value="...">
    #   <input type="hidden" name="tipodoc" value="...">
    #   <input type="hidden" name="pathdoc" value="...">
    #   (pode ter outros campos escondidos - capturamos todos, nao so
    #   esses tres, para nao perder nenhum token/campo de seguranca)
    # </form>
    form_download = linha_xml.first.locator('form[action*="downdoc"]')

    # .evaluate le a propriedade JS "action" (nao o atributo cru), entao o
    # navegador ja devolve a URL absoluta, mesmo se o HTML tiver so um
    # caminho relativo.
    action_url = form_download.evaluate("form => form.action")

    # Captura TODOS os campos hidden do formulario automaticamente, em vez
    # de fixar so iddoc/tipodoc/pathdoc - evita perder algum campo extra
    # (ex: token de seguranca) que o servidor exija.
    dados_form = form_download.evaluate(
        """form => {
            const dados = {};
            form.querySelectorAll('input[type="hidden"]').forEach(input => {
                dados[input.name] = input.value;
            });
            return dados;
        }"""
    )

    resposta = page.context.request.post(
        action_url,
        form=dados_form,
        headers={"Referer": page.url},
    )
    if not resposta.ok:
        raise RuntimeError(
            f"Falha ao baixar o XML via {action_url} - status {resposta.status}"
        )

    conteudo = resposta.body()

    # Valida se realmente veio XML (e nao uma pagina de erro/login em
    # HTML). Se nao for, salva o conteudo bruto para diagnostico e avisa
    # claramente em vez de deixar o parser XML quebrar com um erro confuso.
    inicio = conteudo.lstrip()[:200].decode("utf-8", errors="ignore").lower()
    if not inicio.startswith("<?xml") and "<nfse" not in inicio and "<enfse" not in inicio:
        caminho_debug = PASTA_DOWNLOAD / f"debug_resposta_download_{ID_TESTE}.txt"
        caminho_debug.write_bytes(conteudo)
        print(
            f"[ERRO] A resposta do download nao parece ser XML valido. "
            f"Conteudo salvo em: {caminho_debug} (abra esse arquivo e me "
            f"mande o que tem dentro para eu ajustar)."
        )
        return None

    destino = PASTA_DOWNLOAD / (nome_arquivo or f"anexo_{ID_TESTE}.xml")
    destino.write_bytes(resposta.body())
    return str(destino)


# ---------------------------------------------------------------------------
# 4) PREENCHIMENTO DO FORMULARIO
# ---------------------------------------------------------------------------

def limpar_campo_se_zerado(page: Page, texto_label_exato: str):
    """
    Alguns campos as vezes vem com um valor "fantasma" tipo "00000" (em
    outros IDs ja vem vazios). Antes de salvar, apagamos esse lixo para
    nao interferir no preenchimento automatico que o sistema faz depois
    de "Confirmar e Gravar Dados".

    Usa igualdade EXATA do texto do label (nao "contains"), porque varios
    labels parecidos compartilham substring (ex: "LC 116 / 2003:" e
    "Descrição LC 116 / 2003:").
    """
    locator = page.locator(
        f"xpath=//*[normalize-space(text())='{texto_label_exato}']/following::input[1]"
    )
    if locator.count() == 0:
        return
    valor_atual = (locator.first.input_value() or "").strip()
    if valor_atual and _campo_esta_vazio(valor_atual):
        locator.first.fill("")
        print(f"  (limpo) '{texto_label_exato}' continha valor zerado ('{valor_atual}') e foi apagado")


def preencher_formulario_capa_dfe(page: Page, dados: DadosNFSe):
    # Garante que estamos na aba Capa do DFe antes de preencher - depois de
    # baixar o XML na aba Anexos, o robo continuava nela e os campos abaixo
    # ficavam invisiveis/inacessiveis.
    page.get_by_role("link", name="Capa do DFe").click()
    page.wait_for_timeout(300)

    # CNPJ Tomador primeiro: o sistema usa ele para autopreencher
    # Cidade/UF do Tomador sozinho.
    selecionar_cnpj_tomador(page, dados.cnpj_tomador)

    preencher_por_label(page, "Número da Nota", dados.numero_nota, indice=0)
    preencher_por_label(page, "Número da Nota", dados.serie, indice=1)
    preencher_por_label(page, "CNPJ Prestador", dados.cnpj_prestador)
    preencher_por_label(page, "Nome Prestador", dados.nome_prestador)
    preencher_por_label(page, "Cidade do Prestador", dados.cidade_prestador)
    preencher_por_label(page, "UF do Prestador", dados.uf_prestador)
    # Cidade do Tomador / UF do Tomador: NAO preencher - o sistema traz
    # sozinho a partir do CNPJ Tomador selecionado acima.
    preencher_por_label(page, "Valor da Nota", dados.valor_nota)
    preencher_por_label(page, "Valor do Serviço", dados.valor_servico)
    preencher_por_label(page, "Código Verifição", dados.codigo_verificacao)
    preencher_por_label(page, "Data Emissão", dados.data_emissao)
    # Data Vencimento / Data Pagamento: ficam em branco (definido pelo usuario)
    preencher_por_label(page, "Código do Serviço da Nota", dados.codigo_servico)
    # LC 116/2003 (codigo e descricao): NAO preencher manualmente. Segundo
    # combinado, esses campos sao preenchidos automaticamente pelo sistema
    # depois que todo o documento e digitado e o usuario clica em "Salvar".
    # Mas o campo pode vir com um "00000" fantasma - limpamos antes de salvar.
    limpar_campo_se_zerado(page, "LC 116 / 2003:")


def salvar_dados_nota(page: Page, id_processo: str):
    """
    Clica em "Confirmar e Gravar Dados" e aguarda o processamento
    terminar (overlay "Gravando dados da nota..." aparece e depois some).
    """
    page.locator("#GravarDadosNotaServ").click()

    # O overlay pode aparecer e sumir rapido - tentamos capturar o
    # aparecimento, mas nao travamos se ele ja tiver sumido rapido demais.
    try:
        page.wait_for_selector("text=Gravando dados da nota", state="visible", timeout=5000)
    except Exception:
        pass

    page.wait_for_selector("text=Gravando dados da nota", state="hidden", timeout=30000)
    print(f"  [OK] ID {id_processo}: dados gravados com sucesso.")


def encaminhar_para_consultas_cadastrais(page: Page, id_processo: str):
    """
    Depois de salvar, o formulario reabre com os botoes de acao no topo.
    O robo abre o dropdown "Encaminhar" e clica em
    "Encaminhar p/ Consultas Cadastrais". Essa opcao dispara um confirm()
    nativo do navegador ("Finalizar Tarefa?") - registramos um handler
    para aceitar automaticamente, senao o clique trava esperando resposta.

    ATENCAO: o dropdown "Encaminhar" tem 6 opcoes e todas usam a MESMA
    funcao JS fetch_finish(id, modelo, N) - so o ultimo numero (N) muda.
    Por isso localizamos pelo TEXTO exato do link, e nao pelo onclick.
    """
    page.once("dialog", lambda dialog: dialog.accept())

    page.locator('button.dropdown-toggle:has-text("Encaminhar")').click()
    page.wait_for_timeout(300)

    link_consultas = page.get_by_role(
        "link", name="Encaminhar p/ Consultas Cadastrais"
    )
    link_consultas.click()
    page.wait_for_timeout(500)
    print(f"  [OK] ID {id_processo}: encaminhado para Consultas Cadastrais.")


# ---------------------------------------------------------------------------
# 5) FLUXO COMPLETO: extrai do XML, preenche, salva e encaminha
# ---------------------------------------------------------------------------

def processar_id(page: Page, id_processo: str):
    """
    Abre o processo, checa se tem XML nos Anexos, extrai os dados e
    preenche o formulario (Capa do DFe).

    Regra combinada: se nao houver XML, ou se algum campo obrigatorio
    nao for encontrado, o ID e pulado e sinalizado para revisao manual -
    nesse caso o robo NAO mexe em nenhum campo da tela.
    """
    print(f"--- Processando ID {id_processo} ---")
    abrir_processo_por_id(page, id_processo)

    caminho_xml = procurar_xml_nos_anexos(page)
    if not caminho_xml:
        print(f"[REVISÃO MANUAL] ID {id_processo}: XML não encontrado nos Anexos.")
        return None

    dados = extrair_dados_nfse(caminho_xml)

    faltando = [c for c in CAMPOS_OBRIGATORIOS if not getattr(dados, c)]
    if faltando:
        print(
            f"[REVISÃO MANUAL] ID {id_processo}: campos obrigatórios "
            f"ausentes no XML: {faltando}."
        )
        return None

    print(f"[OK] ID {id_processo}: dados extraídos do XML:")
    for campo, valor in asdict(dados).items():
        print(f"  {campo}: {valor}")

    print(f"Preenchendo formulário do ID {id_processo}...")
    preencher_formulario_capa_dfe(page, dados)
    print(f"[CONCLUÍDO] ID {id_processo}: formulário preenchido.")

    print(f"Salvando dados do ID {id_processo}...")
    salvar_dados_nota(page, id_processo)

    print(f"Encaminhando ID {id_processo} para Consultas Cadastrais...")
    encaminhar_para_consultas_cadastrais(page, id_processo)

    return dados


def main():
    with sync_playwright() as p:
        # Conecta no Chrome que voce ja abriu e logou manualmente
        # (veja instrucoes de CDP_URL no topo do arquivo).
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        input(
            "Confirme que a aba esta na tela inicial do sistema (Workspace) "
            "e pressione Enter para o robo comecar..."
        )

        processar_id(page, ID_TESTE)

        input("Teste finalizado. Pressione Enter para encerrar...")
        # Nao fechamos o navegador, pois ele nao foi aberto pelo robo.


if __name__ == "__main__":
    main()
