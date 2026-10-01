# Perfil restrito WAHA — experimental

Base: https://github.com/devlikeapro/waha, branch core, commit aa0663b1870e384e392d828b8cdf4470ac70eb74.

O arquivo waha-core-restricted.patch altera src/main.ts e adiciona src/core/assistant-restricted.ts. Preserve a licença upstream e marque as alterações da versão distribuída. WAHA_CORE_LICENSE contém a licença da revisão inspecionada.

Aplicação em checkout limpo dessa revisão:

```bash
git apply --check /caminho/waha-core-restricted.patch
git apply /caminho/waha-core-restricted.patch
```

Habilitar exige WAHA_ASSISTANT_RESTRICTED=true, chave WAHA_API_KEY não vazia, WHATSAPP_DEFAULT_ENGINE=WEBJS e todas estas variáveis em false:
WAHA_DASHBOARD_ENABLED, WHATSAPP_SWAGGER_ENABLED, WAHA_EVENTS_DOWNLOAD_MEDIA, WAHA_API_DOWNLOAD_MEDIA, WHATSAPP_DOWNLOAD_MEDIA.

O perfil mantém os guards de autenticação upstream. Aceita apenas consulta/criação/inicialização da sessão default, QR, envio de texto individual sem prévia de link e consulta pontual de mensagem sem mídia. Recusa origem de navegador, configuração extra de sessão, grupos, mídia e demais rotas; fecha upgrades WebSocket. Não aceita URLs arbitrárias para download.

Teste isolado da política, com Node 24 que executa TypeScript removendo tipos:

```bash
node /caminho/assistant/tests/test_waha_restricted.mjs /caminho/waha/src/core/assistant-restricted.ts
```

Esse teste passou após aplicar o patch numa cópia limpa. Não substitui yarn build, testes Nest completos, varredura de dependências/imagem e teste de sessão WEBJS. A política não concede permissão WhatsApp por conversa nem implementa um registro próprio de IDs permitidos; o vínculo ao primeiro contato é validado pelo Assistant.

O instalador incluído aceita imagens oficiais fixadas por digest. Ele NÃO constrói, aplica, seleciona nem ativa este fork. Antes de distribuir uma imagem própria, adicionar suporte explícito ao seu repositório/digest no instalador e validar o perfil na imagem. Não há digest de fork aprovado nesta entrega.
