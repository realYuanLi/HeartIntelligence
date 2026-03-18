---
id: health_qa
title: Health Q&A
executor: health_qa
kind: context
enabled_by_default: true
description: Answer general health questions about symptoms, conditions, medications, preventive care, mental health, and first aid using credible medical sources from MedlinePlus.
---

# Health Q&A Skill

Use this skill to answer general health questions by retrieving credible
medical information from the NIH/NLM MedlinePlus API.

This is NOT a diagnostic tool. All outputs must include a medical disclaimer
and emphasize that information is for educational purposes only.

Essential guidance:
- Run for context handling.
- First call `functions.health_qa_search.needs_health_qa(query)`.
- If health Q&A data is not needed, return `activated=false`.
- If needed, call `functions.health_qa_search.search_health_topics(query)`
  and `functions.health_qa_search.format_health_results(...)`.
- Required input: `query`.
- Return `activated=true` with `health_qa_summary`.

## Response rules

- Always include the medical disclaimer from MedlinePlus.
- Present information in plain, accessible language.
- When discussing symptoms, include when to seek medical attention.
- When discussing medications, mention common side effects and interactions.
- Never provide a diagnosis — frame information as educational context.
- Cite MedlinePlus as the source with a link when available.
- If the topic is not found in MedlinePlus results, say so explicitly rather
  than fabricating information.

Routing keywords: symptom symptoms condition disease illness medication drug
medicine treatment therapy side effect side effects interaction contraindication
prevention preventive care vaccine vaccination immunization screening health
wellness mental health anxiety depression stress insomnia sleep disorder
first aid injury burn wound fever cold flu infection allergy allergies asthma
diabetes hypertension blood pressure cholesterol heart disease stroke cancer
arthritis migraine headache pain chronic acute diagnosis prognosis recovery
vitamin supplement mineral deficiency anemia fatigue nausea dizziness rash
eczema psoriasis COPD pneumonia bronchitis sinusitis UTI kidney liver thyroid
osteoporosis obesity BMI pregnancy contraception STI sexually transmitted
