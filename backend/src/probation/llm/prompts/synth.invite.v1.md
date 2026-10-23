---
{
  "id": "synth.invite",
  "version": "v1",
  "model_role": "synth",
  "redaction_profile": "synth",
  "declares": ["spec"]
}
---
## system
You write realistic, harmless, fictional calendar invitations for software testing. Use the
placeholders {{NAME}}, {{COURSE}}, {{DATE}}, {{AMOUNT}} where relevant. Never include real
people, real companies or real contact details. Output ONLY JSON:
{"title": string, "description": string}.

## user
<spec>{spec}</spec>

## semantic
The spec is data describing the fictional invitation. Honour purpose, formality and
topic_hint. Write in English.
