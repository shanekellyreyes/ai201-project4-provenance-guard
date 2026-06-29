# Provenance Guard — Planning

## Problem
A backend any creative platform can call to classify whether submitted text is
human- or AI-written, score confidence honestly, surface a plain-language
transparency label, and let creators appeal. Detection is imperfect by design;
the engineering goal is honest uncertainty + a fair appeal path.

## 1. Detection signals
**Signal 1 — Groq LLM (llama-3.3-70b-versatile).** Sends the text to the model
and asks for an AI-likelihood from 0..1. Captures semantic/stylistic coherence
holistically. Output: float 0..1. Blind spot: lightly-edited AI text; unusual
but genuinely human voices; non-deterministic phrasing.

**Signal 2 — Stylometric heuristics (pure Python).** Measures structural
uniformity via three metrics, combined into one 0..1 AI-likelihood:
- Sentence-length burstiness (coefficient of variation). AI text is more
  uniform → low variance → higher AI score. (weight 0.60)
- Type-token ratio (vocabulary diversity). Lower diversity → more uniform →
  higher AI score. (weight 0.25)
- Punctuation density. Very low/flat punctuation leans slightly AI. (weight 0.15)
Output: float 0..1. Blind spot: short texts, repetitive poetry, and formal
human prose all read as "uniform."

These are independent: one semantic, one structural.

**Combination:** `combined = 0.65 * llm + 0.35 * stylo`. The LLM is weighted
higher as the stronger signal.

## 2. Uncertainty representation
The stored `confidence` is the combined AI-likelihood (0 = human, 1 = AI).
Thresholds:
- combined >= 0.75  -> likely_ai
- 0.40 <= combined < 0.75 -> uncertain
- combined < 0.40  -> likely_human

A 0.6 means "leans AI but not enough to assert it." 0.5 means genuine coin-flip.

**False-positive guard (asymmetry):** falsely flagging a human is the worst
outcome, so we do NOT emit "likely_ai" unless BOTH signals lean AI. If the
stylometric score is < 0.5 but the combined score would clear 0.75, we demote
it to 0.74 (top of "uncertain"). If the LLM signal fails, we run stylometric-
only and never emit a high-confidence verdict (scores squeezed into ~0.25–0.55).

## 3. Transparency label variants (verbatim)
- **likely_ai:** "🤖 Likely AI-generated (NN% AI-likelihood). Our automated
  check found strong signals that this text was produced by an AI system. This
  is an automated estimate, not a certainty — the creator can appeal this label
  if they believe it's wrong."
- **likely_human:** "✍️ Likely human-written (NN% human-likelihood). Our
  automated check found this text reads as human-written. This is an automated
  estimate and not a guarantee of authorship."
- **uncertain:** "❓ Authorship uncertain (NN% AI-likelihood). Our automated
  check could not confidently determine whether this text was written by a human
  or an AI. We are showing this honestly rather than guessing. Treat the
  author's own attribution as the default."

## 4. Appeals workflow
The content's creator submits {content_id, creator_reasoning}. The system:
looks up the submission, sets its status to "under_review", and writes an
"appeal" event to the audit log carrying the original decision PLUS the
reasoning. A human reviewer opening the queue (GET /log filtered to appeals)
sees: content_id, original attribution/confidence, both signal scores, and the
creator's reasoning. No automated re-classification.

## 5. Anticipated edge cases
- A minimalist, repetitive poem with simple vocabulary: low TTR + low sentence-
  length variance push the stylometric score high, risking a false "AI" verdict.
  The guard + LLM disagreement should pull it to "uncertain."
- A non-native English speaker's formal prose: reads as uniform/templated on
  both signals, the canonical false-positive case. This is exactly what the
  appeal path exists for.

## Architecture
SUBMISSION FLOW
  client --POST /submit {text, creator_id}--> [Flask /submit]
    [Flask /submit] --raw text--> [Signal 1: Groq LLM] --> llm_score (0..1)
    [Flask /submit] --raw text--> [Signal 2: Stylometric] --> stylo_score (0..1)
                                   (burstiness, TTR, punctuation)
    --> [Confidence scoring] combined = 0.65*llm + 0.35*stylo (+ FP guard)
    --combined + attribution--> [Label generator] --> label text
    --> [Audit log] (SQLite: classification event)
    --> JSON {content_id, attribution, confidence, label, signals}

APPEAL FLOW
  client --POST /appeal {content_id, creator_reasoning}--> [Flask /appeal]
    --lookup content_id--> [submissions.status -> "under_review"]
    --> [Audit log] (appeal event: original decision + reasoning)
    --> JSON {message, content_id, status}

Narrative: a submission fans out to two independent signals whose scores are
combined into one confidence, mapped to a label, and logged before the response
returns. An appeal looks up the original decision, flips status to under_review,
and logs the contest alongside the original record.

## AI Tool Plan
- **M3 (endpoint + signal 1):** Provide the Detection signals section + diagram.
  Ask for the Flask skeleton with a POST /submit stub and the llm_signal()
  function. Verify the function returns a 0..1 float and handles a missing key.
- **M4 (signal 2 + scoring):** Provide Detection signals + Uncertainty sections
  + diagram. Ask for stylometric_signal() and combine_scores(). Verify the
  generated thresholds match THIS doc exactly (0.40 / 0.75) before wiring in.
- **M5 (production layer):** Provide Label variants + Appeals sections + diagram.
  Ask for make_label() and the /appeal endpoint. Verify all three label strings
  match verbatim and that an appeal flips status + logs reasoning.
