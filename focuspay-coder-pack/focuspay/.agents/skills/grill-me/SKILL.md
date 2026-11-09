---
name: grill-me
description: >-
  Strongly clarifies a vague or mixed user request before any implementation.
  Use only when the user invokes /grill-me, or when they ask to grill / прожарить
  the request. Parses verbs, screen path, and out-of-scope; asks hard questions;
  does not write code until one goal is confirmed.
disable-model-invocation: true
---

# /grill-me — прожарка контекста

Разобрать слова человека до кода. Не смешивать несколько просьб. Не тащить гипотезы из прошлого чата.

## Сделай сейчас

1. Разбор слов: глагол, экран (`/x8`, `/ops`, бот), что менять, что **не** трогать.
2. Несколько задач в одном сообщении — список. Сейчас делаем **последнюю** явную фразу («нужно / сделай / давай / измени»), остальное — out of scope, пока не скажут.
3. Задай 3–7 жёстких вопросов, пока нет: path экрана, один критерий готовности, out-of-scope.
4. Не пиши код и не планируй деплой, пока человек не подтвердил **одну** цель.
5. После ответов — короткий план из его слов, затем работа.

## Запрещено

- Подменять цель на `/exchange` / LIVE RATES без явного «на сайте».
- Делать findings агентов / прошлый чат требованием.
- Автокоммит, автодеплой, секреты.
