Este projeto consiste em um robô de automação desenvolvido em **Python** utilizando a biblioteca **Playwright**, projetado para automatizar o processamento de Notas Fiscais de Serviço Eletrônicas (NFS-e) no sistema WS360.

O objetivo desta solução é eliminar tarefas repetitivas de extração e inserção de dados, reduzindo o tempo operacional e minimizando erros humanos no fluxo de trabalho.

## 🚀 Funcionalidades

O robô executa um fluxo completo de ponta a ponta:
- **Conexão via CDP:** Conecta-se a uma sessão do Chrome já autenticada pelo usuário, preservando o contexto de login.
- **Navegação Inteligente:** Navega pelo sistema, pesquisa processos por ID e interage com modais de tarefa.
- **Extração de Dados:** Localiza arquivos XML nos anexos, processa o conteúdo e extrai informações cruciais utilizando a biblioteca `xml.etree.ElementTree`.
- **Preenchimento Automático:** Preenche os campos do formulário web de forma inteligente, respeitando as validações e o preenchimento automático nativo do sistema.
- **Finalização:** Encaminha a tarefa para o próximo estágio do workflow de forma autônoma.

## 🛠️ Tecnologias Utilizadas

- **Python 3**
- **Playwright (sync_api):** Para automação da navegação web.
- **Chrome DevTools Protocol (CDP):** Para conexão com o navegador.
- **ElementTree:** Para parsing e extração de dados de arquivos XML.

## 📋 Pré-requisitos

1. **Python instalado.**
2. **Playwright:**
   ```bash
   pip install playwright
   playwright install chromium
