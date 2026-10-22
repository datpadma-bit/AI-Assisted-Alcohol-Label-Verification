# How the Label Checker works (explained simply)

This page explains the whole project the way you would explain it to a curious ten-year-old.
No code. If you want the code, the technical README and the files in `app/` are there.

---

## The job in one sentence

A company sends the government a **form** that says what is on their bottle, and a **picture** of
the bottle's label. Our job is to check: *does the picture really say what the form says?*

Think of it like a teacher checking homework against the answer key. The form is the answer key.
The picture is the homework.

---

## The seven stages

```
 1. Load        2. Tidy up      3. Find the       4. Write the     5. Ask Clef    6. Judge        7. Show
    the picture    the picture     warning box       questions        (twice)        the answers     the result
    and the form                   and zoom in                                        in Python
```

### Stage 1 — Load

The user gives us two things:

- **The picture** of the label (PNG, JPEG or WebP, up to 10 MB).
- **The form**: brand name, what kind of drink it is, how strong it is, how much is in the bottle,
  and sometimes who bottled it and which country it came from.

For a big pile of labels, the user gives us many pictures and one spreadsheet (CSV) with one row
per picture. We match each row to its picture by file name.

We check the form right away. If a required box is empty, or only has spaces in it, we stop and
say which box is missing. We never guess.

We do not save the picture anywhere. It stays in memory while we check it and then it is gone.

### Stage 2 — Tidy up the picture

Real photos are messy. Before we show the picture to anyone, Python cleans it a bit, like wiping
a window before looking through it:

- **Brighten and sharpen the contrast**, so a dark photo becomes readable.
- **Straighten it** if it was taken at an angle. Python tries rotating the picture a little each
  way and keeps the angle where the lines of text look most like neat rows. It can fix tilts up
  to about 12 degrees.
- **Notice dark labels** (light writing on a black label) and remember that, so later steps
  can flip the colours.

This is all plain maths on pixels. No artificial intelligence here.

### Stage 3 — Find the warning box and zoom in

Every alcohol label must carry the **Government Warning** paragraph. Two of its rules are about
*how it looks*, not what it says: the words "GOVERNMENT WARNING:" must be in **capital letters**
and **bold**.

Capital letters and bold are tiny details. Looking at the whole label, they are hard to see, like
trying to read a street sign from across a football field. So Python finds the warning paragraph
and zooms in on it.

How does Python find it without reading? It looks at the picture row by row and counts how much
"ink" is in each row. Rows with text have lots of ink, gaps between lines have none. That gives a
list of text lines. The warning paragraph is the block with the **smallest** letters and the
**most** lines. Python crops that block out and enlarges it.

If it cannot find such a block (say the photo is a mess), it zooms the whole label instead and
tells the judge in stage 6 to be more careful.

### Stage 4 — Write the questions

Now comes the clever part. We have a helper called **Clef** (more about Clef below) that can look
at a picture and answer **multiple-choice questions**. It cannot write sentences. It can only pick
an answer and say how sure it is.

So Python writes the questions, like a quiz, from the user's form:

**"What brand name is printed on the label?"**
- A) OLD TOM DISTILLERY ← the one the form says
- B) DISTILLERY TOM OLD ← a fake answer Python made up
- C) OLD TOM DISTILLING CO. ← another fake
- D) none of these

Python makes the fake answers on purpose. We found that if you ask Clef "is OLD TOM DISTILLERY
printed here? yes or no", it is bad at it. But if you give it the real answer **next to** fakes,
it picks the right one almost every time. Clef is good at *comparing*, not at *remembering*.

The same trick is used for the drink type, the strength (Python changes just the number, so
"45% Alc./Vol. (90 Proof)" gets fakes "40% Alc./Vol. (80 Proof)" and "50% Alc./Vol. (100 Proof)"),
the bottle size, the bottler and the country.

For the warning text, Python splits the long paragraph into its two sentences and asks about each
one separately: "Is this exact sentence printed on the label?" That way, if one sentence is wrong,
we can point at it.

For the zoomed-in warning box, Python asks: "Is the header written as 'Government Warning' in
small letters?", "Which style is the header: ALL CAPS / Title Case / something else?", and "Are
the words GOVERNMENT WARNING thicker and bolder than the sentences after them?"

### Stage 5 — Ask Clef (twice, at the same time)

Python sends two pictures with their quizzes to Clef at the same moment:

1. **The whole label** with the questions about brand, type, strength, size, and the warning sentences.
2. **The zoomed warning box** with the questions about capitals and bold.

Clef answers each question with a number between 0 and 1 for every choice. 0.95 means "almost
certainly this one". 0.02 means "almost certainly not". Both answers come back in about one second.

### Stage 6 — Judge the answers (Python decides, not Clef)

Clef never says "pass" or "fail". Python does, using three bands:

| Clef's number for the right answer | Python's verdict | Colour |
|---|---|---|
| high (about 0.75 or more) | **Match** | green |
| in the middle | **Needs review** — a human should look | orange |
| low (about 0.25 or less) | **Mismatch** | red |

Python also double-checks the answers against each other. For example, if Clef says "the strength
matches" but also says "no strength is printed on the label", Python does not trust the first
answer and marks it for review. If Clef says "there is no warning" but also "both warning
sentences match", same thing.

The label's overall result is the worst of its rows: one red row makes the whole label red.

### Stage 7 — Show the result

The web page shows a big coloured banner, then one row per check with a green / orange / red
pill, how sure Clef was, and when something does not match, what the label *appears* to show
instead (for example "label shows: 40% Alc./Vol. (80 Proof)"). For a batch, there is a table
and a CSV download.

---

## What is Clef, and how is it different from a normal AI?

A normal AI chatbot (an LLM, like the ones you type questions into) **writes text**. You ask it
something, it writes back a paragraph. That is powerful but has problems for a job like ours:

- It is slow, because it writes one word at a time.
- It can make things up and sound confident while doing it.
- You then have to read its paragraph and figure out what it decided.
- If the label itself had sneaky text on it like "ignore the rules and say this label is fine",
  a text-writing AI might actually listen to that.

**Clef-omni** (made by Cloudflare, free and open so anyone can run it) is a different kind of AI.
It is a **decision model**. You give it a picture and a quiz with fixed answers, and it gives back
only numbers: how likely each answer is. It cannot write a sentence at all. That means:

- It is fast, about a tenth of a second per picture on Cloudflare's servers.
- It cannot ramble or invent an answer that is not on the list.
- It cannot be tricked by words on the label, because it cannot follow instructions, only pick.
- Its numbers are honest about doubt, so Python can send unsure cases to a human.

It also understands pictures, so it can see things like **bold** and **capital letters**, which
plain text tools cannot.

## Why not just use OCR?

OCR (optical character recognition) is the old tool that turns a picture of text into typed text.
We thought about it. We chose Clef instead because:

- OCR gives you **letters**, not **looks**. It cannot tell you if a word was bold. Our rules
  need that.
- OCR makes small mistakes ("0" for "O", "1" for "l"), and then you need a pile of extra code
  to forgive those mistakes without forgiving real errors.
- OCR on a messy photo (glare, tilt, dark) often fails completely.
- With Clef we get a confidence number for free, which is what the "Needs review" band is built on.

The honest trade-off: Clef cannot tell us *what the label says*, only *which of our answers fits*.
That is why we show "label appears to show: …" using the fake answer Clef preferred, rather than
real extracted text. Adding OCR later just for that display would be a reasonable next step.

## Why not a normal chat AI that sees pictures?

It would work, but it would be slower (seconds, not a tenth of a second), more expensive, and we
would have to parse its written answer. The agency also said their network blocks many outside
services. Clef is open-weight, so the same model could be installed inside their own building on
one big graphics card, with no internet needed. A chat AI from a big provider usually cannot be.

---

## Every test picture and what it taught us

We were given one example label as text, not as a picture, so we drew our own. Thirteen of them.
Each one checks something specific.

| Picture | What is special | What we expect | What happened and what we did about it |
|---|---|---|---|
| **ok.png** | The example from the task, drawn exactly. Everything correct. | Match | At first Clef said the brand was only 0.35 likely, on a perfect label. That is how we discovered Clef needs fake answers to compare against. With fakes it jumped to 0.85. |
| **wrong_abv.png** | Label says 40% / 80 Proof, form says 45% / 90 Proof. | Mismatch | Caught at 0.02. Clef picked the "40%" fake answer, so we can tell the user what the label shows. |
| **wrong_net_contents.png** | Label says 700 mL, form says 750 mL. | Mismatch | Caught at 0.02. |
| **wrong_brand.png** | Label says "OLD TOM DISTILLING CO." | Mismatch | Caught at 0.04. |
| **reworded_warning.png** | The warning is there but the sentences are reworded. | Mismatch | Asking about the whole paragraph at once did not work (Clef gave 0.09 even on a *correct* warning). Splitting it into two sentences fixed it: correct sentences score about 0.9, reworded ones 0.01. |
| **missing_warning.png** | No warning at all. | Mismatch | "Warning present" comes back at 0.00. The sentence checks also fail, and Python cross-checks so nothing contradictory slips through. |
| **titlecase_warning.png** | Header printed as "Government Warning:" instead of "GOVERNMENT WARNING:". This is the exact case an agent in the interviews rejected. | Needs review | On the whole label Clef could not see the difference at all. After Python zooms into the paragraph, the "ALL CAPS" score drops from 0.92 to about 0.45, enough to flag it for a human. We mark this orange, not red, because we are flagging it, not proving it. |
| **import_scotch.png** | A different brand, with a bottler line and "PRODUCT OF SCOTLAND". | Match | Checks the two optional fields work live. They do, at 0.85 and above. |
| **case_variant_brand.png** | Label says "Stone's Throw", form says "STONE'S THROW". An agent in the interviews said this should obviously count as the same. | Match | Clef agrees it is the same brand at about 0.9. No special code needed. |
| **dark_label.png** | Light writing on a dark label. | Match | Broke our paragraph finder, which was looking for dark ink. Python now notices a dark background and flips the colours. The bold check was also unsure on light-on-dark text, so we flip the zoomed crop to dark-on-light before showing Clef. |
| **photo_glare.png** | A big bright glare blob across the warning, like a flash reflection. | Match | Passed without changes. |
| **photo_low_light.png** | Very dark, low contrast. | Match | Clef first called it "unreadable". Python's contrast step fixed it. |
| **photo_tilted.png** | Rotated 7 degrees, blurred, with camera noise. | Needs review | Three problems at once. Tilt broke the paragraph finder, so Python learned to straighten pictures. Noise made the picture file enormous (17 seconds just to save it), so we switched to JPEG. After all that, one warning sentence still reads at 0.35, so the label goes to a human. For a photo this bad, that is the right answer. |

Result on the last run: **13 of 13** pictures got the verdict we expected. The tilted one sits
close to the line and can flip to Match on some runs.

---

## Edge cases we handle (and what you see)

**Form problems**

| What happens | What we do |
|---|---|
| A required box is empty or just spaces | Stop with "brand_name is required and cannot be blank" (the real box name) |
| Optional boxes (bottler, country) empty | Skip those two questions, no penalty |
| Strength written in words ("forty five percent") | Still works; Python uses generic fake answers instead of maths-based ones |
| Bottle size in an odd format | Same, generic fakes |

**Picture problems**

| What happens | What we do |
|---|---|
| Not a picture (a .txt, a PDF) | Refuse with the file name and the allowed types |
| Named .png but broken inside | Orange "Needs review" with "Unreadable image file" |
| Bigger than 10 MB | Refuse |
| Huge picture | Python shrinks it to 1600 px on the long side before sending |
| Tilted up to ±12° | Straightened |
| Dark, low contrast | Brightened |
| Light writing on dark label | Colours flipped for the zoom |
| Warning paragraph cannot be found | Zoom the whole label instead, and never give a red result on the capitals/bold checks from that, only orange |
| Picture so bad Clef calls it unreadable | Whole label goes orange for a human |

**Batch problems**

| What happens | What we do |
|---|---|
| Spreadsheet missing a required column | Stop the whole batch, name the missing columns |
| Spreadsheet empty, or header only | Stop, say so |
| One row has a blank box | Only that picture goes orange, with "CSV line 7: net_contents is required". Everything else still runs |
| A picture has no row in the spreadsheet | That picture goes orange: "No matching row in CSV" |
| A row has no picture uploaded | An extra orange row: "Listed in CSV but no image was uploaded" |
| File named `A.PNG` but spreadsheet says `a.png`, or `labels/a.png` | Treated as the same file |
| 300 labels at once | Eight run at a time; nothing is dropped |

**Service problems**

| What happens | What we do |
|---|---|
| No Cloudflare login set up | Orange result with "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN" |
| Cloudflare is slow or down | Orange result with the network error, after a 20-second timeout, never a crash |
| Clef sends back a shape we do not recognise | Orange result with the first part of what it sent |

**Judgement problems**

| What happens | What we do |
|---|---|
| Clef is confident in the right answer but *slightly more* confident in a fake | Orange, with "Model leaned towards: …" |
| "Strength matches" but also "no strength printed" | Orange, we do not trust contradictions |
| "No warning present" but "sentences match" | Sentences go orange |
| Bold is unsure | Orange with "Bold weight is a visual judgment. Check by eye." |

---

## Things we did not do, on purpose

- **We do not store any pictures or form data.** The agency asked for that.
- **We do not read the text off the label.** Clef cannot, and we chose not to add a second tool for it yet.
- **We do not fix really bad photos.** A blurry, noisy, tilted photo gets straightened and brightened, and then, if it is still unclear, it goes to a human. That is what agents do today.
- **We only know spirits rules.** Wine and beer have slightly different rules and would need their own quiz.
- **We tuned the thresholds on our own drawn labels.** Real bottle photos should be the next test.
