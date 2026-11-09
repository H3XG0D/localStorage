---
type: research
tags: [research, android, licenses, font]
status: done
updated: 2026-10-07
source: "github.com/googlefonts/onest OFL.txt; name table of Onest-Regular"
---

# Onest — шрифт Android-клиента

Date: 2026-10-07

## Source

- [github.com/googlefonts/onest](https://github.com/googlefonts/onest) — `OFL.txt`
- [github.com/simpals/onest](https://github.com/simpals/onest) — авторы проекта
- Name table вшитого `Onest-Regular`: Copyright 2021 The Onest Project Authors, SIL Open Font License 1.1

## Summary

Onest — гротеск с кириллицей. Лицензия SIL OFL 1.1: шрифт можно встраивать в коммерческое приложение и распространять вместе с ним. Нельзя продавать сам файл шрифта отдельно. Текст лицензии нужно хранить рядом с файлами.

В Android-клиент взяты веса 400, 500, 600, 700 и 800 из поставки Google Fonts / `@expo-google-fonts/onest`. Копия OFL: `clients/android/third_party/onest/OFL.txt`. JS-обёртка Expo (MIT) в приложение не входит.

## Relevance to FocusVPN

Макет интерфейса задаёт Onest. Шрифт пермиссивный и не тянет GPL в APK. Канон лицензии — строка в [[OPEN_SOURCE]].

## Related

- [[OPEN_SOURCE]]
- [[MOC/Research]]
