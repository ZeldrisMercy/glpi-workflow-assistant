# Segurança e estabilidade — RC4

## Escopo desta versão

Nova criação de proativos, Bridge 2.4.0 e correção Abrir conversa. Não substitui a análise histórica de WAHA por uma nova auditoria completa. WAHA continua fixado no digest estável anterior e com as restrições de instalação existentes.

## Controles aplicados

- Rotas da revisão protegidas pela verificação local existente; entrada do Bridge exige autenticação do pareamento.
- Rascunhos e planos vinculados ao servidor GLPI e ao usuário autenticado. Plano expira em dez minutos; digest incorreto, revisão alterada ou pendências impedem execução.
- Prioridade elevada depende da revisão local, ignorando a autorização enviada pela IA. Entidade, categoria e atores são confirmados em consultas ao GLPI; ambiguidade não é resolvida por palpite.
- A execução aceita somente o plano persistido no servidor. Caminhos locais de anexos não são aceitos do contrato da IA. Imagens são bytes base64, PNG/JPEG/WebP, limite de 4 MiB por arquivo, 30 por envio e limite total de transporte.
- HTML do conteúdo é escapado. URLs remotas de imagens fornecidas pela IA não são baixadas. Prévia exige propriedade do rascunho e usa no-store/nosniff/same-origin.
- Banco do diário e arquivos de evidência com modo 0600, diretório de imagens 0700. SQLite com gravação síncrona e reserva antes das mutações.
- Operação e etapas possuem marcadores estáveis. Resultados incertos não autorizam repetição cega. Upload perdido permanece para conferência manual por não existir reconciliação confiável em todas as instalações GLPI.
- Print de contexto não é enviado. O mapa de evidências é local ao proativo; captura de prompt não combina arquivos antigos por posição.
- O marcador de proativo é verificado pelo monitor antes da resposta inicial automática e do envio WAHA. Não remova o marcador do conteúdo enquanto a automação estiver ativa.
- Revisão é uma ação humana anterior à criação. Lote não é transação distribuída: sucesso individual é preservado e falha parcial é exibida.

## Limites operacionais explícitos

Esta versão não assegura que regras internas GLPI deixarão os dados inalterados; verifica o resultado e relata divergência. Notificações/e-mails dependem do GLPI. Fuso usado na abertura é o configurado na Central; configure-o de acordo com o servidor.

Não há limpeza automática do diário de proativos e das suas evidências nesta candidata: preservação permite recuperação e evita nova criação após resposta incerta. Inclua a pasta de dados existente no backup local; ela contém informação de atendimento. Não publique essa pasta.

A captura de timestamp e prints depende de o Bridge acompanhar o envio do prompt. Respostas antigas ou sem correspondência com o prompt atual não são encaminhadas automaticamente como novo proativo. Importação manual permanece disponível com revisão dos dados reais.

Nenhuma conta de WhatsApp foi vinculada ou mensagem real enviada pelos testes desta entrega. Não há promessa de risco zero nem de validação real de produção.
