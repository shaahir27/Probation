---
{
  "id": "wording",
  "version": "v1",
  "model_role": "wording",
  "redaction_profile": "template",
  "declares": ["template"]
}
---
## system
Reword the template into one clear English sentence. Keep every number exactly as
written. Add no new facts and no new numbers. Output ONLY JSON: {"sentence": string}.

## user
<template>{template}</template>

## semantic
The sentence keeps the template's action, its target and its polarity. Numbers may change
order only if the meaning is unchanged; nothing else may be added.
