# TTB Label Verifier — Clef-omni + Python prototype

Checks an alcohol beverage label image against the application data: brand name, class/type,
alcohol content, net contents, optional bottler and country of origin, and the Government Warning
(present, each sentence word-for-word, header in ALL CAPS, header bold). Single-label and batch modes.

## How it works

Plain-language walkthrough of every stage, every test image and every edge case: **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)**. Step-by-step test instructions: **[follow_test.md](follow_test.md)**.

**Clef-omni is the witness, Python is the judge.**

[Clef-omni](https://huggingface.co/cloudflare/clef-omni) is Cloudflare's open-weight (Apache 2.0)
multimodal *decision* model. It takes an image plus a fixed set of typed questions and returns a
calibrated probability for every predefined answer in one forward pass. It never generates text,
so it is fast (~150 ms per call), cheap, and cannot be prompt-injected by text on the label.

Everything else is plain Python (`app/`):

| Step | Who | What |
|---|---|---|
| 1 | Python | Builds the questions from the user's application data, the way a human agent reads a label: *WHAT brand is printed? WHAT alcohol content? HOW is the header written?* |
| 2 | Python | For every field, generates two plausible **wrong answers** (decoys) from the user's value, e.g. `45% Alc./Vol. (90 Proof)` → `40% Alc./Vol. (80 Proof)`, `50% Alc./Vol. (100 Proof)`. Clef is a comparison model: asked "is X printed?" alone it scores ~0.05 even on a perfect label; asked to pick between X and decoys it scores ~0.9 and picks the wrong label's value at ~0.04. |
| 3 | Python | Splits the Government Warning into its two numbered sentences and asks about each one separately, so the agent sees *which* sentence is wrong. |
| 4 | Python | Normalises contrast, straightens a tilted photo (projection-profile deskew), handles light-on-dark labels, then finds the warning paragraph with a row-ink profile (no OCR) and zooms it. Clef reads letter case and font weight reliably only from this crop. Pure Pillow; there is no second model. |
| 5 | Clef | Two calls run in parallel: the full label (what is printed) and the zoomed crop (how the header is printed). |
| 6 | Python | Cross-checks the answers (e.g. "ABV matches" vs "no ABV visible"; "no warning present" vs "sentences match") and converts probabilities to **Match / Needs review / Mismatch** with per-check thresholds measured on sample labels. Overall result is the worst field. |

Measured live on the thirteen generated labels in `samples/` (`uv run python scripts/live_check.py`):

| label | result | what Python flagged |
|---|---|---|
| ok.png | Match | — |
| wrong_abv.png | Mismatch | Alcohol content 0.02, label shows `40% Alc./Vol. (80 Proof)` |
| wrong_net_contents.png | Mismatch | Net contents 0.02 |
| wrong_brand.png | Mismatch | Brand name 0.04 |
| reworded_warning.png | Mismatch | Warning sentence (1) 0.01, sentence (2) 0.14 |
| missing_warning.png | Mismatch | Warning present 0.00 |
| titlecase_warning.png | Needs review | Header ALL CAPS 0.48, "Possible 'Government Warning' in title case" |
| import_scotch.png (bottler + origin) | Match | — |
| case_variant_brand.png (Stone's Throw vs STONE'S THROW) | Match | — |
| dark_label.png | Match | — |
| photo_glare.png | Match | — |
| photo_low_light.png | Match | — |
| photo_tilted.png (7°, blur, noise) | Needs review | Warning sentence (1) 0.35 |

12 of 13 match the expected verdict every run; the tilted photo sits near a threshold. Single labels take
0.7–1.9 s including both Clef calls and the Python image prep.

## Run

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
copy .env.example .env      # then fill in Cloudflare account id + Workers AI token
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Tests (no network): `uv run pytest`.
Live check on the samples: `uv run python scripts/live_check.py`.
Regenerate samples: `uv run python scripts/make_samples.py`.

Docker: `docker build -t label-verifier . && docker run -p 8080:8080 --env-file .env label-verifier`

## Deploy to Cloudflare Containers

The FastAPI app runs in the Docker container, and a Cloudflare Worker forwards requests to it.
This uses Cloudflare Containers (Workers Paid plan required); it is not a Cloudflare Pages
deployment. The Worker configuration is in `wrangler.jsonc` and `cloudflare/worker.js`.

1. Install and start Docker Desktop, then sign in to Cloudflare from the repository root:

   ```bash
   npx wrangler@4.152.0 login
   ```

2. Deploy the Worker and container from a terminal with Docker running:

   ```bash
   npx wrangler@4.152.0 deploy --config wrangler.jsonc
   ```

3. Add the Workers AI credentials to the Worker as secrets. Wrangler prompts for each value;
   do not paste credentials into source files or commit them:

   ```bash
   npx wrangler@4.152.0 secret put CLOUDFLARE_ACCOUNT_ID --config wrangler.jsonc
   npx wrangler@4.152.0 secret put CLOUDFLARE_API_TOKEN --config wrangler.jsonc
   ```

   Create the API token from Cloudflare's Workers AI page. A custom token needs **Workers AI
   Read** and **Workers AI Edit** permissions. The Worker passes these secrets to the container
   when it starts. Visit the `workers.dev` URL printed by Wrangler to start the app.

The container needs outbound internet access to call `api.cloudflare.com`; the Worker enables
this when starting the container. To redeploy code changes, run the Wrangler deploy command again
from a machine with Docker running. Do not use a Cloudflare Pages build's `npx wrangler deploy`
command for this setup: Pages build environments do not provide the local Docker engine Wrangler
needs to build and push the Container image. If this GitHub repository is connected to a Pages
project, disable that Pages project's automatic build/deploy for this repository before pushing
deployment changes; deploy the Worker and Container with Wrangler instead.

## API

- `POST /api/verify` — multipart: `image` + form fields `brand_name, class_type, alcohol_content, net_contents, [bottler_name_address], [country_of_origin]`
- `POST /api/batch` — multipart: `images[]` + `manifest` CSV (`filename,brand_name,class_type,alcohol_content,net_contents,bottler_name_address,country_of_origin`; see `samples/manifest.csv`). Add `as_csv=true` for a CSV download.

Each field in the response carries `verdict`, `confidence`, a human `note`, and `seen` (what the label appears to show when it does not match).

## Things learned about Clef-omni (and how the code handles them)

- **It compares, it does not recall.** Yes/no questions about a literal value are unreliable; multiple choice with decoys is reliable. All identity fields are choice questions.
- **Option IDs leak into the answer.** The same question scores 0.85 with ids `expected/d1/d2/none` and 0.3 with `wrong_1/wrong_2` or `a/b/c/d`. The ids are fixed in `verifier.py` with a comment.
- **Long exact-text comparison is weak** (~0.09 on a perfect warning). Per-sentence questions score 0.85-0.95 for correct text and 0.01-0.2 for reworded text.
- **Letter case and bold need a zoom.** On the full label title case was invisible; on the Python crop it drops the ALL CAPS score from 0.92 to 0.44, enough to flag for a human.
- **Where things are, it cannot say.** Asked which quarter of the label holds the warning it answered wrong every time, so the crop is done in Python.
- Live `noul` answers arrive as `{"type": "noul", "noul": p}`; `choice` as `{"choice", "probabilities", "confidence"}`; `score` as `{"score", "legend", "probabilities"}`.

## Assumptions and trade-offs

- **Network:** the hosted prototype calls one domain, `api.cloudflare.com`. The weights are open, so
  the same model can be self-hosted (one H200-class GPU, ~64 GB) inside the agency's Azure tenant;
  set `CLEF_BASE_URL` to a SystemOne-compatible endpoint and no outbound calls are needed.
- **Title case is flagged, not proven.** The ALL CAPS score for a title-case header lands at ~0.44,
  which the thresholds map to Needs review rather than Mismatch. A human confirms by eye.
- **No text extraction:** Clef says *which* predefined answer fits, not *what the label says*. The
  `seen` field uses the best-scoring decoy as a hint. A local OCR evidence layer is the next step.
- **Imperfect photos:** Python deskews up to ±12°, normalises contrast, and sends JPEG to keep noisy photos small. Heavy blur still lands on Needs review, which is the intended outcome. Legibility is scored and "unreadable" forces review.
- **Privacy:** images are processed in memory and never written to disk or logged.
- **Scope:** built around distilled spirits (the sample label). Wine and beer rules are an extension.
- **Calibration:** thresholds were tuned on thirteen synthetic labels. Real bottle photos need checking next.
