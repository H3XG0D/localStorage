---
type: moc
tags: [moc, security]
status: active
updated: 2026-08-11
---

# MOC — Security

Карта безопасности и криптоконтрактов.

## Спеки

- [[SECURITY]] — угрозы, пароли, JWT, KEK, rate limits
- [[OPEN_SOURCE]] — лицензионный гейт (нет GPL в binary)

## ADR

- [[005-configuration-security]] — Ed25519 ConfigParts; ключи клиента на устройстве
- [[006-auth-session]] — Access JWT EdDSA; refresh rotation + reuse detection
- [[004-node-agent]] — mTLS агента

## Plans

- [[plans/M3]] — envelope + signing + versioning design (**approved**; Ready=YES)

## Non-negotiables

- Client private keys never leave the device
- CP signs ConfigParts (Ed25519)
- Access JWT = EdDSA (Ed25519)
- No GPL/AGPL in product binary

## Связано

- [[Home]] · [[INDEX]] · [[MOC/Architecture]] · [[MOC/Decisions]] · [[TODO]]
