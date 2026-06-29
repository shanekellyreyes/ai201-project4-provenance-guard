# Provenance Guard

A backend any creative platform can plug into to classify whether submitted text
is human- or AI-written, score confidence honestly, surface a plain-language
transparency label, and let creators appeal a classification they think is wrong.

Detection is imperfect by design — perfect AI detection is an unsolved problem.
The engineering goal here is honest uncertainty plus a fair appeal path, not a
binary verdict that pretends to a certainty it doesn't have.

## Run it

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "GROQ_API_KEY=your_key_here" > .env
python app.py
```

The server runs on **port 5001**. (Port 5000 is grabbed by macOS AirPlay
Receiver on recent macOS, which silently intercepts requests — if you're on a
Mac, either use 5001 as configured or disable AirPlay Receiver in System
Settings.)

Endpoints:
- `POST /submit` — `{text, creator_id}` → classification + confidence + label
- `POST /appeal` — `{content_id, creator_reasoning}` → flips status to under_review
- `GET /log` — recent audit-log entries as JSON

## Architecture overview

A submission to `POST /submit` fans out to two independent detection signals: a
Groq LLM that judges the text holistically, and a pure-Python stylometric
function that measures structural uniformity. Their two scores combine into a
single confidence value, which maps to one of three transparency labels. The
full decision — both signal scores, the verdict, the confidence — is written to
a SQLite audit log before the JSON response returns to the caller, carrying a
`content_id` the creator can use to appeal. `POST /appeal` looks up that original
decision, flips the content's status to `under_review`, and logs the contest
alongside the original record. (Full diagram in planning.md.)

## Detection signals

I use two signals that capture genuinely different properties of the text — one
semantic, one structural — so they fail in different places.

**Signal 1 — Groq LLM (llama-3.3-70b-versatile).** Sends the text to the model
and asks for an AI-likelihood from 0 to 1, plus one sentence of reasoning. This
captures semantic and stylistic coherence the way a human reader would — tone,
phrasing, whether it "reads" generated. I chose it because it catches things no
formula can. Its blind spot: it's confidently wrong on lightly-edited AI text
and on unusual-but-genuinely-human voices, and it's non-deterministic.

**Signal 2 — Stylometric heuristics (pure Python).** Measures structural
uniformity through three metrics combined into one 0–1 score:
- **Sentence-length burstiness** (coefficient of variation, weight 0.60) — AI
  text trends uniform, human writing is bumpier.
- **Type-token ratio** (vocabulary diversity, weight 0.25) — lower diversity
  leans AI.
- **Punctuation density** (weight 0.15) — flat/sparse punctuation leans mildly AI.

I chose it because it's fully independent of the LLM — it knows nothing about
meaning, only shape. Its blind spot: anything naturally uniform reads as AI to
it — short texts, repetitive poetry, and dry formal prose all trip it.

## Confidence scoring

The two signals combine as `combined = 0.65 * llm + 0.35 * stylo`, weighting the
LLM higher as the stronger signal. The combined score maps to three bands:
- `>= 0.75` → **likely_ai**
- `0.40 – 0.75` → **uncertain**
- `< 0.40` → **likely_human**

**False-positive guard.** On a writing platform, falsely flagging a human's work
as AI is the worst outcome — so the system refuses to emit "likely_ai" unless
*both* signals lean AI. If the stylometric score is below 0.5 but the combined
score would clear 0.75, it's demoted to 0.74 (top of "uncertain"). If the LLM
signal fails entirely, the pipeline runs stylometric-only and squeezes scores
into a mid band so a degraded run can never assert a confident verdict.

**Validation.** I tested four deliberately chosen inputs spanning the range and
confirmed the scores separate meaningfully rather than flipping at a single
point. Two examples with noticeably different confidence (both real `/submit`
outputs):

- **Lower-confidence:** a casual first-person restaurant review →
  confidence **0.182** → `likely_human` (llm 0.2, stylo 0.15)
- **Higher-confidence:** a highly repetitive, low-vocabulary paragraph →
  confidence **0.958** → `likely_ai` (llm 0.99, stylo 0.899)

That ~0.78 spread between clearly-human and clearly-AI text is the evidence the
scoring produces meaningful variation, not a constant.

## Transparency label (all three variants)

The label shown to a reader changes with the confidence band. Exact text:

| Verdict | Label text |
|---|---|
| likely_ai | 🤖 Likely AI-generated (NN% AI-likelihood). Our automated check found strong signals that this text was produced by an AI system. This is an automated estimate, not a certainty — the creator can appeal this label if they believe it's wrong. |
| likely_human | ✍️ Likely human-written (NN% human-likelihood). Our automated check found this text reads as human-written. This is an automated estimate and not a guarantee of authorship. |
| uncertain | ❓ Authorship uncertain (NN% AI-likelihood). Our automated check could not confidently determine whether this text was written by a human or an AI. We are showing this honestly rather than guessing. Treat the author's own attribution as the default. |

`NN` is filled in at runtime with the actual percentage. The "uncertain" variant
deliberately defers to the author's own attribution — it never accuses, because
an uncertain score is exactly the case where a false accusation does the most
damage.

## Appeals workflow

A creator submits `{content_id, creator_reasoning}` to `POST /appeal`. The system
looks up the original submission, sets its status to `under_review`, and writes
an `appeal` event to the audit log that carries the original decision
(attribution, confidence, both signal scores) *plus* the creator's reasoning. A
human reviewer opening the queue (via `GET /log`, filtered to appeal events) sees
everything needed to judge the contest in one place. No automated
re-classification — a contested call goes to a human.

## Rate limiting

`10 per minute; 100 per day` on `/submit`, via Flask-Limiter (in-memory store).
Reasoning: a real creator submits their own work occasionally and may resubmit a
few times after edits, so 10/minute never gets in a legitimate user's way. But
an adversary scripting the endpoint to fingerprint the detector or flood the log
would blow past that instantly, and the 100/day ceiling caps sustained abuse
without throttling even an unusually prolific writer. The numbers are sized to
realistic single-creator usage, not pulled arbitrarily.

Evidence (12 rapid requests — first 10 succeed, rest are blocked):

```
200
200
200
200
200
200
200
200
200
200
429
429
```

## Audit log (sample)

Every classification and appeal writes a structured JSON entry. Sample from
`GET /log` showing all three verdicts and one appeal:

```json
{
  "event_type": "appeal",
  "content_id": "8cb1e749-6d74-49f8-879c-63e8ee76335b",
  "creator_id": "test-user-1",
  "attribution": "likely_human",
  "confidence": 0.182,
  "llm_score": 0.2,
  "stylo_score": 0.15,
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
  "timestamp": "2026-06-29T07:26:55.704122+00:00"
}
{
  "event_type": "classification",
  "content_id": "dc33f401-516f-4fd4-ad57-6c5a8c15bd19",
  "creator_id": "test-user-4",
  "attribution": "likely_ai",
  "confidence": 0.958,
  "llm_score": 0.99,
  "stylo_score": 0.899,
  "status": "classified",
  "appeal_reasoning": null,
  "timestamp": "2026-06-29T07:26:33.002804+00:00"
}
{
  "event_type": "classification",
  "content_id": "2e552f88-8dfd-4a46-8b9b-a7d76a6f4849",
  "creator_id": "test-user-2",
  "attribution": "uncertain",
  "confidence": 0.675,
  "llm_score": 0.8,
  "stylo_score": 0.442,
  "status": "classified",
  "appeal_reasoning": null,
  "timestamp": "2026-06-29T07:23:49.057891+00:00"
}
```

## Known limitations

The stylometric signal is unreliable on **short text** (roughly under four
sentences). With so few sentences, the burstiness metric is statistically noisy,
and type-token ratio stays high simply because short passages don't repeat
words — so genuinely AI-generated short text reads as more "human" than it is.
This is visible in my own testing: the canonical clearly-AI sample
("paradigm shift... it is important to note... furthermore...") scored only
**0.442** on stylometry and landed at `uncertain` (0.675) rather than
`likely_ai`, because its brevity starved the structural metrics. This isn't a
bug to paper over — it's an inherent property of stylometry on short inputs, and
it's exactly why the appeal path exists. A production version would gate the
stylometric signal's weight below a minimum length and lean harder on the LLM
for short submissions.

## Spec reflection

**How the spec helped:** writing the three label strings and the band thresholds
into planning.md *before* any code meant the label function had an exact target
to implement against — there was no ambiguity about what "uncertain" should say
or where the cutoffs fell, so the implementation was mechanical instead of
guesswork.

**Where it diverged:** my planning.md threshold table didn't include the
false-positive guard or the degraded-mode squeeze. I added both after testing
showed the LLM alone could push borderline human text over 0.75 — which is the
one thing the system most needs to avoid. So the implementation requires *both*
signals to lean AI before it will assert "likely_ai," a safety constraint the
original spec's clean threshold table didn't capture.

## AI usage

1. **Flask skeleton + first signal.** I gave an AI tool my detection-signals
   section and the architecture diagram and asked it to generate the Flask app
   skeleton and the `llm_signal()` function. The first version crashed when the
   API key was missing and didn't handle the model returning markdown-fenced
   JSON. I added the `try/except` with an explicit `missing_api_key` path and
   the regex that strips ```json fences before parsing, so a missing key
   degrades gracefully instead of taking down the endpoint.

2. **Confidence scoring.** I asked it to generate `combine_scores()` from my
   uncertainty section. The generated version drifted from my spec — it used
   0.7/0.3 thresholds instead of the 0.75/0.40 I'd written — and it omitted the
   false-positive guard entirely. I corrected the thresholds to match planning.md
   and added the guard that demotes to "uncertain" when only one signal leans AI.