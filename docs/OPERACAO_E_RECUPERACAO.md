# Operação, backup e recuperação — 3.3.0

## Antes de atualizar

Guarde o .deb e a imagem da versão anterior. A atualização interrompe o Assistant antes do backup; há uma janela de indisponibilidade. Não atualize enquanto uma aplicação no GLPI estiver em andamento. O backup automático cobre /var/lib/glpi-assistant/data, com snapshot consistente do SQLite; ele não inclui o volume da sessão WAHA.

Para backup manual, pare o serviço e execute:

```bash
sudo systemctl stop glpi-assistant.service
sudo glpi-assistant-backup
sudo systemctl start glpi-assistant.service
```

O comando imprime o caminho criado em /var/backups/glpi-assistant. Não compartilhe esse arquivo. Se o backup falhar, não prossiga com atualização ou descarte de dados. O preinst tenta reativar o serviço anterior em falha de backup; isso não é um rollback automático de qualquer falha posterior do instalador.

## Diagnóstico mínimo

```bash
glpi-assistant status
journalctl -u glpi-assistant.service -n 80 --no-pager
```

Não publique saída sem sanitização. Confirme que a interface abre apenas em http://127.0.0.1:8765, a versão é 3.3.0 e o GLPI usa HTTPS com CA confiável. Configurar a CA no sistema é preferível a ignorar certificado; a aplicação não oferece bypass TLS.

Se Docker estiver ausente/parado, corrija o serviço e conclua a configuração do pacote com `sudo dpkg --configure glpi-assistant`. Se o download/build da imagem falhar, não considere a instalação concluída. Consulte o erro antes de tentar novamente.

## Resultado incerto

Timeout após envio pode significar que a operação foi concluída no servidor. Confira a conversa ou a tarefa no GLPI antes de qualquer nova tentativa. Não apague os registros de idempotência para “destravar”. Para entrega WhatsApp pendente, use Verificar entrega; esse botão não reenvia.

No fechamento parcialmente aplicado, os itens não confirmados ficam disponíveis. Gere nova revisão a partir do estado atual do GLPI. Não reenvie um lote inteiro supondo que nada foi gravado.

## Rollback

1. Pare o Assistant. Preserve uma cópia privada do estado atual, mesmo se houver erro.
2. Reinstale o .deb anterior com apt. A versão anterior também precisa da sua imagem/dependências disponíveis.
3. Restaure dados somente se houver incompatibilidade ou corrupção comprovada. Não restaure automaticamente um banco antigo: isso pode apagar reservas de mensagens e permitir duplicação.
4. Para restaurar backup, valide o arquivo e seus caminhos em diretório temporário privado. Pare o serviço, substitua o diretório data pela cópia validada e preserve a cópia atual fora dele. Não extraia arquivos de origem desconhecida como root.
5. Confira versão, integridade SQLite, configuração, fila e registros de envio antes de reativar automações.

Backup de sessão WAHA exige parar esse container e copiar o volume por mecanismo administrado. O container “previous” preservado pelo instalador usa o mesmo volume: não execute ambos ao mesmo tempo. Uma mudança de formato da sessão pode impedir retorno à imagem anterior.

## Incidente

Pause a automação na interface e pare o WAHA se houver suspeita de envio indevido. Em suspeita de comprometimento, desvincule o dispositivo no WhatsApp do celular, revogue/rotacione tokens GLPI e chave WAHA e preserve logs/dados de forma privada. Investigue a estação antes de reconectar uma conta.

A remoção/purge da 3.3.0 preserva /var/lib/glpi-assistant. Isso evita perda acidental, mas exige descarte explícito pelo administrador, incluindo volume WAHA, perfil da extensão e backups, depois de revogar acessos. Não há rotina automática de eliminação completa.

## Manutenção

Revisar advisories e dependências antes de cada atualização; registrar digest da imagem usada, resultado de testes e data. Não usar latest para WAHA. Homologar restauração e fluxo de entrega antes de ampliar o uso. O pacote não agenda essa manutenção automaticamente.
