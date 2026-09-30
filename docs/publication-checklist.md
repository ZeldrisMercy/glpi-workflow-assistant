# Publication Checklist

## P0 — não publicar sem isso

- [ ] Titularidade/autorização verificada.
- [ ] Histórico Git sanitizado.
- [ ] Secret scan limpo.
- [ ] Nenhum token/cookie/sessão.
- [ ] Nenhum cliente real.
- [ ] Nenhum usuário real.
- [ ] Nenhum ticket real.
- [ ] Nenhum telefone/e-mail real.
- [ ] Nenhum domínio/URL interna.
- [ ] Nenhum IP de cliente.
- [ ] Nenhum log/banco real.
- [ ] Nenhum screenshot não sanitizado.
- [ ] Nenhuma sessão WAHA.
- [ ] `.deb` inspecionado.

## Código
- [ ] `.env.example`.
- [ ] defaults seguros.
- [ ] loopback confirmado.
- [ ] Bridge sem credenciais.
- [ ] logs com redaction.
- [ ] dependências/licenças revisadas.

## Criação proativa
- [ ] schema validado.
- [ ] deduplicação testada.
- [ ] Dry Run testado.
- [ ] aprovação humana obrigatória.
- [ ] fixtures 100% sintéticas.
- [ ] não afirmar homologação enquanto estiver apenas em desenvolvimento.

## Docs
- [ ] README PT.
- [ ] README EN.
- [ ] architecture.
- [ ] security model.
- [ ] threat model.
- [ ] install.
- [ ] usage.
- [ ] troubleshooting.
- [ ] changelog.
- [ ] roadmap.

## Release evidence
- [ ] CI verde.
- [ ] SBOM.
- [ ] SHA-256.
- [ ] release notes.
- [ ] rollback.
