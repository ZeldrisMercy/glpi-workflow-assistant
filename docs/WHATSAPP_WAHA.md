# WhatsApp no GLPI Assistant 3.2.10

## Instalação

No Linux onde o GLPI Assistant está instalado, extraia o pacote e execute dentro da pasta extraída:

```bash
sudo apt install ./glpi-assistant_3.2.10_all.deb
sudo glpi-assistant-waha
```

A instalação precisa de internet para baixar imagens Docker/dependências. O instalador opcional usa a imagem gratuita `devlikeapro/waha`, não WAHA Plus, resolve a imagem uma vez e registra seu ID localmente. Ele não ativa envios. Se a porta local 3000 já estiver ocupada, resolva o conflito antes de instalar; esta candidata espera WAHA em 127.0.0.1:3000.

Abra http://127.0.0.1:8765 → **Bridge e IA → WhatsApp**. Clique em **Conectar WhatsApp**; o QR aparece quando a sessão está pronta. No celular, abra WhatsApp Business → Dispositivos conectados → Conectar dispositivo. Confira o número exibido no Assistant.

Para primeiro contato automático, mantenha o monitor ativo em Minha central, marque **Enviar automaticamente somente em novas atribuições a mim** e salve a automação. A próxima consulta completa registra a fila existente sem enviar mensagens. Somente atribuições detectadas depois dessa consulta podem disparar. A detecção usa o intervalo do monitor (padrão 120 segundos; mínimo 60), não um webhook instantâneo.

## O que cada ação faz

| Ação | Comportamento |
| --- | --- |
| Nova atribuição a você | Envia o modelo de primeiro contato, se a automação estiver ativa e o contato for inequívoco. |
| Chamado que já estava na fila ao ativar | Não envia automaticamente. |
| Retomar atendimento | Um clique envia o modelo de continuidade pelo WAHA, sem abrir WhatsApp ou pedir outra confirmação. Disponível mesmo com envio automático desativado, desde que a sessão esteja conectada. |
| Editar retomada | Abre um texto editável apenas para aquele envio; depois use Enviar retomada. |
| Contatar | Abre diretamente o WhatsApp Web com o primeiro contato preenchido. O envio nesse caminho é manual. |
| Editar mensagem, no card expandido | Personaliza primeiro contato antes de abrir o WhatsApp Web. |
| Pausar envios | Desativa os futuros primeiros contatos automáticos. Não cancela mensagens já submetidas. |

Os dois modelos ficam em **Minha central → Preferências de acompanhamento e mensagem**. A aba **Todos em acompanhamento** torna os chamados da fila inicial acessíveis para retomada. A Central exibe o resultado da tentativa sem abrir outra tela.

## Persistência e falhas

A sessão WAHA é persistida no volume Docker `glpi-assistant-waha-sessions`. Reiniciar o container ou computador preserva esse volume. Outro QR pode ser necessário se o WhatsApp invalidar a sessão ou se o dispositivo for desconectado. Não exclua o volume ao reiniciar.

O serviço e o monitor funcionam com o navegador fechado, mas a máquina precisa estar ligada. O registro de tentativas fica no banco persistente do Assistant. O primeiro contato é limitado a uma tentativa por chamado e técnico/servidor; sair e voltar para a fila não repete essa tentativa.

Em timeout após submeter a mensagem, o resultado fica **incerto** e não há reenvio automático. **Aceito pelo WAHA** não significa entregue ou lido. Consulte a conversa antes de repetir manualmente. A retomada possui identificador de tentativa e bloqueio adicional por um minuto para evitar duplo clique. Se o navegador perder a resposta, mantém o mesmo identificador naquela aba.

Se o WhatsApp estiver offline, houver mais de um requerente, telefone inválido ou mudança de atribuição, o contato não será enviado. Essas falhas não geram uma fila de disparos atrasados; use Contatar ou Retomar atendimento depois de conferir os dados. Se a leitura do chamado falhar antes da preparação, a falha também aparece na consulta da Central. A implementação não verifica propriedade real do número: usa o telefone do atendimento/cadastro no GLPI.

## Segurança e limites

A API fica ligada apenas a 127.0.0.1, usa chave aleatória e não compartilha credenciais com a extensão. O WAHA é um serviço separado; seus controles estão agrupados visualmente com o Bridge. Nenhuma imagem de evidência é enviada ao WAHA pelo Assistant. O WAHA mantém sua própria sessão WhatsApp.

Esta integração é não oficial e está sujeita a desconexões ou restrições do WhatsApp. O software é gratuito; energia, máquina ou hospedagem continuam sendo recursos necessários.

Fontes técnicas consultadas: https://waha.devlike.pro/docs/how-to/sessions/ · https://waha.devlike.pro/docs/how-to/security/ · https://waha.devlike.pro/docs/how-to/storages/ · https://waha.devlike.pro/docs/how-to/send-messages/

## Bridge 2.2.8-dev

Para aplicar a redução do aviso no ChatGPT, atualize também a extensão. O pacote contém o XPI de desenvolvimento e a pasta `extension` dentro do ZIP de código-fonte. O XPI não é assinado: no Firefox padrão, use carregamento temporário em `about:debugging` apontando para `extension/manifest.json`, ou assine/distribua pelo fluxo Mozilla já usado no projeto. Recarregue o chat após atualizar. Não é necessário atualizar o Bridge para o WAHA funcionar.

## Rollback

Primeiro pause envios automáticos em Bridge e IA. Para interromper o WAHA, use `sudo docker stop glpi-assistant-waha`. Preserve o volume. Reinstale o .deb anterior se necessário; preserve `/var/lib/glpi-assistant/data`. O pacote não remove uma versão anterior dos seus backups nem migra credenciais GLPI.
