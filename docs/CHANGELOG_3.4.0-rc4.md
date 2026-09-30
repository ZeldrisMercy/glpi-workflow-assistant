# GLPI Assistant 3.4.0-rc4 — proativos pelo chat

Aplicação: 3.4.0-rc4 · Debian: 3.4.0~rc4-1 · Bridge: 2.4.0.

## O que mudou e por quê

- **Criar proativos**: nova área de revisão com vários chamados por prompt e quantidade livre de atividades. Permite catalogar atendimentos simples e complexos sem forçar o roteiro de fechamento de chamados existentes.
- **Cadastro por atendimento**: entidade e categoria são obrigatórias e resolvidas no GLPI. Requerente e técnico usam o usuário autenticado por padrão; outros nomes precisam ser informados e resolvidos sem ambiguidade. Grupos e modalidade das atividades podem ser revisados.
- **Data original**: o Bridge registra o horário de envio do prompt com fuso; a aplicação converte para o fuso configurado da Central. Ausência ou incompatibilidade mantém pendência, sem inventar data.
- **Requisição e prioridade**: tipo Requisição, Baixa/Média por padrão. Alta ou superior exige escolha explícita na revisão local. Se regras do GLPI alterarem os campos, o resultado permanece para conferência.
- **Prints por proativo**: contrato declara a posição da imagem no prompt, seu ID local e as atividades correspondentes. Imagens de contexto são excluídas; imagens finais sem arquivo ou sem atividade associada bloqueiam a criação. Prints de um prompt anterior não são reaproveitados por posição.
- **Revisão em lote**: edição invalida somente o plano afetado; campos resolvidos aparecem com nome e ID; criação sequencial, comprovante com link para GLPI, sucesso sai da lista e falha fica para continuar. A atualização periódica não interrompe digitação no editor.
- **Recuperação persistente**: SQLite registra a operação antes das mutações remotas. Resposta perdida na criação ou tarefa é reconciliada por marcador; nenhuma segunda criação automática quando o resultado permanece incerto. Upload incerto exige conferência, sem duplicar anexos.
- **Proativos sem automações de contato**: marcador no conteúdo exclui estes chamados da T01 pública automática e dos novos envios WAHA. As atividades informadas no próprio proativo continuam sendo criadas.
- **Abrir conversa**: inclui a correção pendente que reutiliza a aba do WhatsApp no mesmo contexto do navegador, com criação de aba somente quando necessário. O Bridge deve estar atualizado e habilitado na aplicação.
- **Tema e responsividade**: revisão própria com azul/roxo discretos, campos agrupados e espaçamento consistente. Verificada em 480, 768 e 1280 pixels, sem transbordamento horizontal nas amostras.

## Como atualizar e usar

1. Instale o `.deb` usando `sudo apt install ./glpi-assistant_3.4.0~rc4-1_all.deb`.
2. Atualize o Bridge para 2.4.0 e recarregue as abas do chat e da aplicação. Firefox: pacote de desenvolvimento; Chromium/Opera: ZIP para carregar a extensão descompactada.
3. Substitua o prompt de formalização pelo arquivo RC4.
4. Informe empresa/unidade, categoria ou contexto suficiente, atendimento e prints na ordem. Para vários proativos, separe claramente cada atendimento.
5. Na área **Criar proativos**, confira os cadastros e evidências, selecione os itens, clique em **Revisar selecionados** e depois **Criar selecionados revisados**.
6. Se a captura original não estiver disponível, importe o contrato e informe o horário real do prompt. Anexe os prints pendentes na própria revisão. Não informe a hora atual como se fosse a original.

**WAHA**: mantém a imagem estável 2026.9.1 já utilizada; este pacote não ativa o fork experimental. Não precisa vincular novamente uma sessão existente para usar proativos.

## Validação e limites

260 testes Python aprovados; 22 scripts JavaScript/DOM e 16 verificações sintáticas aprovados; instalador verificado com simulações, metadados, sintaxe e extração do Debian. Consulte o relatório JSON entregue.

Não houve criação real no seu GLPI, teste de e-mail, Docker instalado ou entrega real do WhatsApp neste ambiente. Permissões, regras locais de prioridade/status e fuso devem corresponder à configuração do seu GLPI. Esta entrega permanece candidata RC4.

Referências de imagens antigas de outros chats não recuperáveis não são tratadas como evidências. A associação automática usa os arquivos capturados no prompt correspondente; dúvidas permanecem para revisão.
