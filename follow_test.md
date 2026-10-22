# follow_test.md — step-by-step test guide

Everything below runs from the project folder. Steps 1–3 need no network. Steps 4 onward call
Clef-omni on Cloudflare Workers AI and need a filled-in `.env`.

---

## 1. Setup

```bash
uv sync
```

Expected: `.venv/` is created, ~30 packages resolved, no errors.

```bash
copy .env.example .env
```

Open `.env` and fill in `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Leave the thresholds as they are.

---

## 2. Unit tests (no network)

```bash
uv run pytest -q
```

Expected: `37 passed`. One deprecation warning from starlette is normal.

What they cover:

| file | what |
|---|---|
| `tests/test_verifier.py` | question building, decoys in the options, thresholds, per-sentence warning, header case/bold, cross-checks |
| `tests/test_decoys.py` | wrong-answer generation from the user's inputs |
| `tests/test_image_prep.py` | Pure-Pillow prep: paragraph finder, light-on-dark labels, deskew of a tilted label, blank and garbage images |
| `tests/test_service.py` | CSV parsing, bad rows reported per row, empty CSV |
| `tests/test_api_batch.py` | `/api/verify` and `/api/batch` end to end with Clef stubbed |

---

## 3. Generate the sample labels

```bash
uv run python scripts/make_samples.py
```

Expected: thirteen PNGs plus `manifest.csv` (application data per file) and `expected.csv`
(expected verdict per file) written to `samples/`:

| file | what it tests | expected |
|---|---|---|
| `ok.png` | README example label, everything correct | match |
| `wrong_abv.png` | label 40% / 80 Proof, application 45% / 90 Proof | mismatch |
| `wrong_net_contents.png` | label 700 mL, application 750 mL | mismatch |
| `wrong_brand.png` | label "OLD TOM DISTILLING CO." | mismatch |
| `reworded_warning.png` | warning sentences reworded | mismatch |
| `missing_warning.png` | no warning at all | mismatch |
| `titlecase_warning.png` | header "Government Warning:" (Jenny's rejection) | needs_review |
| `import_scotch.png` | bottler line + "PRODUCT OF SCOTLAND", all correct | match |
| `case_variant_brand.png` | label "Stone's Throw", application "STONE'S THROW" (Dave's case) | match |
| `dark_label.png` | light text on dark background | match |
| `photo_glare.png` | bright glare blob over the warning | match |
| `photo_low_light.png` | dark, low contrast | match |
| `photo_tilted.png` | tilted 7°, blurred, noisy | needs_review |


---

## 4. Live check against Clef-omni (network)

```bash
uv run python scripts/live_check.py
```

The script reads `manifest.csv`, calls Clef for every label, and compares with `expected.csv`.

Expected last line: `12/13 labels got the expected overall verdict` or `13/13`. Twelve are stable;
`photo_tilted.png` sometimes comes back `match` instead of `needs_review` because its one weak
sentence hovers around the threshold. Every `OK` line should list the flagged field(s) shown in the
table above, e.g. `wrong_abv.png ... flagged: Alcohol content 0.02`.

For full detail on one label:

```bash
uv run python scripts/live_check.py titlecase_warning.png
```

Each label should take 1–2 seconds. If you see `Set CLOUDFLARE_ACCOUNT_ID ...` the `.env` is not filled in.
If you see `Clef HTTP 401/403` the token is wrong or lacks Workers AI permission.

---

## 5. Start the web app

```bash
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. You should see "Alcohol Label Checker" with two tabs.

The sample images are also served at http://127.0.0.1:8000/samples/ok.png etc. so you can download
them to try in the UI.

---

## 6. UI test — one label

Fastest way: at the top of the **One label** tab there is a row of **Test 1 … Test 13** buttons.
Click one and the picture, the form fields, and a line saying what the result *should* be all fill in.
Then press **Check this label**. Test numbers follow the order of the table in step 3
(Test 1 = ok.png, Test 2 = wrong_abv.png, … Test 13 = photo_low_light.png).

Manual way:

1. Tab **One label**.
2. Click the dashed box, choose `samples/wrong_abv.png`. The box turns green and shows the file name.
3. Fill in:
   - Brand name: `OLD TOM DISTILLERY`
   - Class / type: `Kentucky Straight Bourbon Whiskey`
   - Alcohol content: `45% Alc./Vol. (90 Proof)`
   - Net contents: `750 mL`
   - Leave bottler and country blank.
4. Click **Check this label**. Button reads "Checking…" for 1–2 s.

Expected:
- Red banner **❌ Label does not match**
- "Picture readability: partially readable · took ~1500 ms"
- Row **Alcohol content** shows red **Does NOT match**, "(2% sure) · label shows: 40% Alc./Vol. (80 Proof)"
- All other rows green **Matches**: Brand name, Class / type, Net contents, Warning present,
  Warning sentence (1), Warning sentence (2), Warning header ALL CAPS, Warning header bold
- "What the model saw" lists: Alcohol content shown as percent and proof; Warning header looks caps

Repeat with the other samples:

| image | expected banner | expected non-green row |
|---|---|---|
| `ok.png` | ✅ Label matches the application | none |
| `titlecase_warning.png` | ⚠️ Needs a human look | Warning header ALL CAPS — "Please check", note about title case |
| `reworded_warning.png` | ❌ Label does not match | Warning sentence (1) and (2), each with "Expected: …" |

---

## 7. UI test — many labels (batch)

1. Tab **Many labels (batch)**.
2. Either click **Load all sample labels + CSV** (fills both file pickers in one go), or:
   - Label pictures: select all thirteen PNGs in `samples/`.
   - Application CSV: select `samples/manifest.csv`.
4. Click **Check all labels**. Takes roughly 10–15 s for thirteen labels (eight run at a time).

Expected:
- Banner **6 match · 2 need a look · 5 do not match** (the tilted photo may land on match instead, making it 7 · 1 · 5)
- One table row per file; the "Problem fields" column names the same fields as the table in step 3.

5. Click **Download results as CSV**. A `results.csv` downloads with the header
   `filename,overall,legibility,field,verdict,confidence,note,error` and 9 rows per label (11 for `import_scotch.png`, which has bottler and origin).

---

## 8. Error-handling checks (UI or curl)

| what to do | expected |
|---|---|
| Submit one-label form with Brand name empty | browser blocks submit (field is required) |
| Brand name = spaces only | red box: "brand_name is required and cannot be blank" |
| Choose a `.txt` as the picture | red box: "unsupported type text/plain. Use PNG, JPEG or WebP." |
| Rename a text file to `.png` and upload | ⚠️ banner, "Unreadable image file. Please upload a valid PNG, JPEG or WebP." |
| Batch: CSV missing the `net_contents` column | red box: "Bad manifest CSV: CSV is missing columns: ['net_contents']" |
| Batch: one CSV row has blank `net_contents` | that file only: Please check, "CSV line N: net_contents is required and cannot be blank"; other files processed normally |
| Batch: upload an image not listed in the CSV | that file: Please check, "No matching row in CSV (check the filename column)" |
| Batch: CSV lists a file you did not upload | extra row: Please check, "Listed in CSV but no image was uploaded" |
| Batch: file named `A.PNG`, CSV says `a.png` | matches (case and folder ignored) |
| Empty `.env` | ⚠️ banner, "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, or CLEF_BASE_URL." |

curl version of the single call, if you prefer the terminal:

```bash
curl -s -F image=@samples/wrong_abv.png -F brand_name="OLD TOM DISTILLERY" -F class_type="Kentucky Straight Bourbon Whiskey" -F alcohol_content="45% Alc./Vol. (90 Proof)" -F net_contents="750 mL" http://127.0.0.1:8000/api/verify
```

Expected JSON: `"overall":"mismatch"`, and inside `fields` the `abv` entry has `"verdict":"mismatch"` and `"seen":"40% Alc./Vol. (80 Proof)"`.

---

## 9. Docker (optional)

```bash
docker build -t label-verifier .
```

```bash
docker run -p 8080:8080 --env-file .env label-verifier
```

Open http://127.0.0.1:8080 and repeat step 6 with one label.

---

## Known limits to keep in mind while testing

- Title case in the header lands at ~0.44, which is **Needs review**, not Mismatch. A human confirms.
- Confidence numbers move by a few points between runs; verdicts should not.
- Inside a batch the per-row "ms" includes time spent queued at Cloudflare, not just model time.
- Thresholds were tuned on these thirteen synthetic labels only. Real bottle photos are the next test.
