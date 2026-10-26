# How the agent works, step by step

Generated from `agent/pipeline.py` and `agent/prompts.py` by `python scripts/export_pipeline.py`. Do not edit by hand.

Every model call sends the same system prefix, then one task line, then the step's input:

```text
## House rules (docs/00-house-rules.md)
…the one-page writing brief…

## Preferences (preferences.yaml)
…what to apply for, where, how often…

## Master documents (the storybook)
…every file in profile/master…

## Task
<one task line below>
```

**Who runs a step:** *you* in the dashboard; *the model* (`JHA_MODEL`); *the draft model* (`JHA_DRAFT_MODEL`, or the model when there is none); or plain *code*. Models are set in `.env` or on the dashboard's Setup page (see `agent/providers.py`).

**Types:** PDF, DOCX, Audio, Text, Markdown, YAML, JSON, SQLite, PNG, Web page, API, IMAP, SMTP, Click. *Outside* means you, the web or your mailbox.

## 01 · Tell it everything

### Tell it everything

**Runs:** You · `dashboard → Storybook chat (history kept per account)`

**Input**

| Type | What | From |
|---|---|---|
| PDF · DOCX | old résumés, letters, papers | outside |
| Audio | voice memos (M4A, MP3, WAV) | outside |
| Text | what you type or say | outside |

**Output**

| Type | What | To |
|---|---|---|
| PDF · DOCX · Audio | the files (saved to profile/uploads/) | **Add to the storybook** |
| Text | your note | **Add to the storybook** |
| Text | everything you said or dropped, for the form answers | **Standing answers** |
| PDF | a résumé you like | **Learn a style** |

### Add to the storybook

**Runs:** The model · `agent/storybook.py · add_from` · output schema: `Additions`

**Input**

| Type | What | From |
|---|---|---|
| Text | each file's text (PDF and DOCX read, audio transcribed locally) | **Tell it everything** |
| Text | your note | **Tell it everything** |
| Markdown | profile/master/02-experience.md, 03-projects.md | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | Additions {file, entry, line, lenses, source} | **The storybook** |
| Markdown | new lines in profile/master/*.md | **The storybook** |
| Markdown | profile/.versions/<time>/ (Back undoes) | outside |

**Prompt** (`prompts.STORYBOOK_ADD`)

```text
Add what this material says about the person to their storybook. Use only facts the material states: never guess numbers, titles, dates, degrees or tools. Skip anything the storybook already says. One fact per line, résumé-ready, result first when the material gives one. In reference letters keep what the writer says the person did, not the praise. Never turn a relative date ('last spring') into a year. A talk, award or press about a project is a line under that project. Don't add a degree as an entry or a line: the résumé takes education from the standing answers. A file about someone else adds nothing: list it in about_someone_else.
```

> A résumé that is about someone else adds nothing about you; on its own it goes to Learn a style instead.

### Learn a style

**Runs:** The model · `agent/storybook.py · learn_from` · output schema: `Edits`

**Input**

| Type | What | From |
|---|---|---|
| PDF | reference résumé | **Tell it everything** |
| Text | your instruction | **Tell it everything** |
| Markdown | résumé lines, entry by entry | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | Edits {before, after, why} | **The storybook** |
| Markdown | reworded lines | **The storybook** |

**Prompt** (`prompts.STORYBOOK_STYLE`)

```text
Rewrite the person's résumé lines in the style of the reference résumé, following their instruction. Borrow structure, rhythm, verbs and how impact is framed. Keep every fact, number and name the same; add nothing. Return only lines that actually change.
```

### Intake draft (command line)

**Runs:** The draft model (or the model) · `agent/intake.py · python -m agent.run intake` · output schema: `Storybook`

**Input**

| Type | What | From |
|---|---|---|
| PDF · DOCX · Audio · Text | inbox/* | outside |

**Output**

| Type | What | To |
|---|---|---|
| Markdown | profile/master/_intake-draft-<date>.md (you edit it) | outside |

**Prompt** (`prompts.INTAKE`)

```text
Turn the raw material into storybook entries. Every line must be traceable to a file; list contradictions as conflicts; copy the person's own sentences verbatim into voice_samples.
```

### Standing answers

**Runs:** The model · `agent/setup_answers.py · fill_from (in the background of the chat)` · output schema: `Answers`

**Input**

| Type | What | From |
|---|---|---|
| Text | what you said or dropped in the chat | **Tell it everything** |
| Click | the form, to correct or finish it | outside |

**Output**

| Type | What | To |
|---|---|---|
| YAML | profile/standing.yaml | **Answer the form**, **Fill the form** |
| Text | the blanks left, named in the chat and marked on the form | outside |

> Filled from your words and files; you never have to type into the form. Required blanks are marked, never guessed.

### The storybook

**Runs:** Code, no model · `<profile>/master/*.md`

**Input**

| Type | What | From |
|---|---|---|
| Markdown | added lines | **Add to the storybook** |
| Markdown | reworded lines | **Learn a style** |
| Markdown · YAML | fixes you applied | **Learn from notes** |

**Output**

| Type | What | To |
|---|---|---|
| Markdown | profile/master/*.md + preferences.yaml + docs/00-house-rules.md, sent as the system prefix | **Add to the storybook**, **Rank the fit**, **Write the résumé**, **Answer the form**, **Revise the résumé**, **Email applications**, **Cover letter** |

> Files, not a step: every model call reads them, with the house rules and your preferences, as the system prefix.

## 02 · Find and rank

### Find postings

**Runs:** Code, no model · `agent/sources/ · agent/run.py · discover, prefilter, find_jobs`

**Input**

| Type | What | From |
|---|---|---|
| Click | Find matching jobs (1-5), offered in the chat once the storybook is ready | outside |
| API | Greenhouse · Lever · Ashby board APIs, read in parallel | outside |
| Web page | Hacker News, Who is hiring | outside |
| YAML | profile/companies.yaml (watchlist) | outside |
| YAML | preferences.yaml (avoid_keywords) | outside |

**Output**

| Type | What | To |
|---|---|---|
| SQLite | jobs: company, title, location, url, description (talent pools skipped) | **Rank the fit** |

> You start it. The best-ranked jobs are then prepared one by one with no more clicks; each comes back as a Review button.

### Rank the fit

**Runs:** The draft model (or the model) · `agent/jev.py (Jev, TypeSafe) · agent/llm.py · score_jobs_claude_code` · output schema: `JobScore`

**Input**

| Type | What | From |
|---|---|---|
| SQLite | jobs (new) | **Find postings** |
| API | Jev P(fit) per posting, when TYPESAFE_API_KEY is set | outside |
| YAML | profile/roles.yaml | outside |
| Markdown | storybook | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | JobScore {score, role_family, sector, fit_reasons, gaps, hard_blockers, action} | **Write the résumé** |
| SQLite | jobs.status = queued \| skipped | **Write the résumé** |

**Prompt** (`prompts.RANK`)

```text
Judge whether {first_name} is a credible candidate for this posting, as a strict recruiter in that field would. Map it to one role family below; respect that family's seniority guard (cap at 50, action 'maybe'). Work authorisation is settled, so it is never a blocker. Role families: {roles}
```

> Jev rates every posting when its key is saved (Setup → API keys); without it Claude Code rates them, 8 per call, never an API key. Under 50 is never applied to.

## 03 · The résumé and the form

### Write the résumé

**Runs:** The model · `agent/assemble.py → agent/llm.py · align_resume → agent/resume/render.py` · output schema: `Aligned`

**Input**

| Type | What | From |
|---|---|---|
| SQLite | the posting | **Rank the fit** |
| JSON | JobScore | **Rank the fit** |
| Markdown | storybook | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | ResumeContent | **Writing check** |
| PDF | out/resumes/<name>.pdf (one page) | **You review** |
| PNG | out/resumes/<name>.png (preview) | **You review** |

**Prompt** (`prompts.ALIGN`)

```text
Align this one-page résumé to the posting. First list the posting's 5-8 core requirements in its own words. Then rewrite every bullet and project blurb so a reader of this posting recognises their requirements: lead with the outcome or capability the posting asks for, use the posting's own nouns and requirement names where they truthfully describe the work (their word for the role, the activity, the user, the tool), but never its sentence rhythm or adjectives: plain verbs, the person's own voice, so this résumé doesn't read like everyone else's. Where a requirement names a domain or a length of experience, state it explicitly if the record supports it. Use any one posting term at most three times on the page. Order bullets inside each entry by how directly they answer the requirements. The two most recent roles must cover every core requirement between them. Facts are fixed: keep every number, employer, client, title, date and tool exactly as given; never add a tool, metric, client, result or responsibility that isn't already there, and never add what happened next or around it (deployed, adopted, drove adoption, rolled out, alongside a named person, a count in words), and never attach the posting's words as new detail (a platform, a tool, a cadence, a method the line doesn't state); change the framing and the words, never the facts. If a requirement isn't supported, leave it uncovered and name it in gaps. Keep each bullet to one achievement in at most two lines (200 characters including spaces), opening verbs varied. Keep entries, projects and their order as given.
```

> Picks the true lines for the role, then words them in the posting's nouns (never its prose) and orders them by its requirements; the two newest roles cover every core requirement. Facts never change: a new number or outcome keeps the original line. Two lines per bullet at most. The template: header links are words (Website · LinkedIn · GitHub), and every place, roles and schools alike, names its country.

### Writing check

**Runs:** The model · `agent/voicecheck.py (rules) · agent/llm.py · repair_text` · output schema: `Repaired`

**Input**

| Type | What | From |
|---|---|---|
| Text | every bullet, answer and email | **Write the résumé**, **Answer the form**, **Email applications** |
| YAML | profile/learned_patterns.yaml (banned phrases) | outside |

**Output**

| Type | What | To |
|---|---|---|
| Text | the same facts, banned phrases rewritten | **Write the résumé** |
| Text | flags left for you | **You review** |

**Prompt** (`prompts.REPAIR`)

```text
Rewrite the text to fix the listed problems. Same facts, same or shorter length.
```

> The rules are code (agent/voicecheck.py and the phrases you taught it): banned phrases, two lines per bullet, and in cover letters no colons, em dashes, small talk, empty contrasts or wh-clauses. The model only rewrites what they flag.

### Answer the form

**Runs:** The model · `agent/llm.py · answer_form · agent/mission.py` · output schema: `FormAnswers`

**Input**

| Type | What | From |
|---|---|---|
| Web page | the form's fields, read live (label, type, required, options) | outside |
| SQLite | the posting | **Rank the fit** |
| Text | the company's mission, in its own words (agent/mission.py) | outside |
| YAML | profile/standing.yaml | **Standing answers** |
| YAML | profile/saved-answers.yaml (questions you answered before) | **You review** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | FormAnswers {answers, needs_human} | **Fill the form** |
| JSON | needs_human: questions only you can answer | **You review** |

**Prompt** (`prompts.ANSWERS`)

```text
Answer this application form. Anything only {first_name} can answer goes in needs_human with a short reason.
```

**Added when it applies** (`prompts.WHY_US`)

```text
For a why-us question or cover letter (why this company, why this role, what excites you about us): write about the company's culture and this role, never a description of their product (they know their product). Open with one specific thing about how the company works or what it values, in its own words from the posting or the mission notes (a principle, a way of working, a stated belief), and why that suits how the candidate works. Now and then, when the company has stated where it is heading in the next year or two (in the posting or the mission notes), name that near-term vision and the part this role plays in it. Then the role: what this team is asking the person in the seat to do, and the candidate's fit for exactly that, shown through one short story from the record, not adjectives (07-voice.md for character and habits). Never open with the candidate or 'I am writing'. Swap test: delete any sentence that would still be true with another company's name in it. Don't summarize the résumé, don't list what the candidate wants from the job, use a number only if the master documents give it. Let real enthusiasm show, never claim it (no 'passionate'). Professional register: personality shows in what the candidate noticed, decided and built, and a well-placed joke is welcome; casual filler ('I love that', 'I'd love to', 'a lot of') is not. Every sentence must say something specific in precise words: no empty contrasts like 'as something you design for, not something that just happens'. Name things with noun phrases, not wh-clauses: 'nearby friends', not 'who is around'; 'its place in the workflow', not 'where it sits'. No colons and no em dashes; write full sentences. Hype words are not welcome.
```

> A question you answered before is answered again from Saved answers. Arbitration, certifications and export-control declarations always stay yours. Why-us questions add the WHY_US rule: the company's culture and the role, never a tour of their product.

### Fill the form

**Runs:** Code, no model · `agent/apply/fill.py · Playwright · the agent's browser`

**Input**

| Type | What | From |
|---|---|---|
| JSON | FormAnswers | **Answer the form** |
| YAML | standing.yaml | **Standing answers** |
| PDF | the résumé | **Write the résumé** |
| Web page | the employer's form, in the agent's browser profile (data/browser) | outside |

**Output**

| Type | What | To |
|---|---|---|
| PNG | out/screens/app<id>.png (the filled form itself; nothing submitted) | **You review** |

> Reads each radio group's own question, keeps every option, maps answers onto the form's wording (countries, opt-ins). A required field it can't fill becomes a question for you.

### Cover letter

**Runs:** The model · `agent/llm.py · answer_form (why-us and cover-letter questions) · agent/cover.py` · output schema: `FormAnswers`

**Input**

| Type | What | From |
|---|---|---|
| SQLite | posting + research notes | **Rank the fit** |
| Markdown | storybook | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| Text | the cover letter: the third document in review, beside the résumé and the form | **You review** |

**Prompt** (`prompts.WHY_US`)

```text
For a why-us question or cover letter (why this company, why this role, what excites you about us): write about the company's culture and this role, never a description of their product (they know their product). Open with one specific thing about how the company works or what it values, in its own words from the posting or the mission notes (a principle, a way of working, a stated belief), and why that suits how the candidate works. Now and then, when the company has stated where it is heading in the next year or two (in the posting or the mission notes), name that near-term vision and the part this role plays in it. Then the role: what this team is asking the person in the seat to do, and the candidate's fit for exactly that, shown through one short story from the record, not adjectives (07-voice.md for character and habits). Never open with the candidate or 'I am writing'. Swap test: delete any sentence that would still be true with another company's name in it. Don't summarize the résumé, don't list what the candidate wants from the job, use a number only if the master documents give it. Let real enthusiasm show, never claim it (no 'passionate'). Professional register: personality shows in what the candidate noticed, decided and built, and a well-placed joke is welcome; casual filler ('I love that', 'I'd love to', 'a lot of') is not. Every sentence must say something specific in precise words: no empty contrasts like 'as something you design for, not something that just happens'. Name things with noun phrases, not wh-clauses: 'nearby friends', not 'who is around'; 'its place in the workflow', not 'where it sits'. No colons and no em dashes; write full sentences. Hype words are not welcome.
```

> Any 'why us', 'why this role' or cover-letter question. When the employer wants your own first draft, the card says so and waits.

## 04 · You decide

### You review

**Runs:** You · `dashboard → Waiting for review`

**Input**

| Type | What | From |
|---|---|---|
| PDF | résumé | **Write the résumé** |
| PNG | filled form | **Fill the form** |
| Text | cover letter | **Cover letter** |
| JSON | questions for you | **Answer the form** |
| Text | checklist | outside |

**Output**

| Type | What | To |
|---|---|---|
| Click | Approve | **Submit**, **Email applications** |
| Text | Change this résumé: your note, typed or spoken | **Revise the résumé** |
| Text | Reject, with a reason (SQLite feedback) | **Learn from notes** |
| YAML | your answers to questions for you, kept as Saved answers and filled on other applications at once | **Answer the form** |

### Revise the résumé

**Runs:** The model · `agent/run.py · revise · /api/applications/<id>/revise` · output schema: `ResumeContent`

**Input**

| Type | What | From |
|---|---|---|
| Text | your note | **You review** |
| JSON | the current ResumeContent (applications.resume_json) | **Write the résumé** |
| SQLite | the posting | **Rank the fit** |
| Markdown | storybook | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | ResumeContent | **You review** |
| PDF | the same file, re-rendered; a green dot when done | **You review** |

**Prompt** (`prompts.REVISE`)

```text
Revise this one-page résumé as the person asks. Change only what the note asks for; keep everything else as it is. Facts, numbers, titles and dates come from the master documents only: if the note asks for something they don't support, leave it out and say so in tailoring_notes. Keep provenance honest.
```

> A branch: it changes this one application's résumé only. Asks the storybook can't support are left out and noted.

### Learn from notes

**Runs:** The draft model (or the model) · `agent/learn.py` · output schema: `Patches`

**Input**

| Type | What | From |
|---|---|---|
| SQLite | feedback: your notes | **You review** |
| SQLite | rejection reasons | **You review** |
| Markdown | docs/00-house-rules.md | outside |
| YAML | preferences.yaml | outside |

**Output**

| Type | What | To |
|---|---|---|
| JSON | Patches {kind, target, before, after, reason} | **The storybook** |
| SQLite | proposals (you apply or dismiss each) | **The storybook** |

**Prompt** (`prompts.LEARN`)

```text
Propose the smallest patches that would have prevented each problem. Prefer one example row in the brief over a new rule; keep the brief to one page. Use storybook_line only to reword an existing line with the same facts, quoting it exactly in 'before'. Use ban_phrase for a phrase that should never appear. Use preference for changes to what to apply for, where, or how often: replace one exact line of preferences.yaml in 'before' with the edited line in 'after'. Skip notes that need no change.
```

## 05 · Out the door, and back

### Submit

**Runs:** Code, no model · `agent/run.py · submit_approved · agent/apply/fill.py · Playwright, visible`

**Input**

| Type | What | From |
|---|---|---|
| Click | approved applications only | **You review** |
| JSON | FormAnswers | **Answer the form** |
| PDF | résumé | **Write the résumé** |
| Web page | the employer's form | outside |

**Output**

| Type | What | To |
|---|---|---|
| Web page | the submitted application | outside |
| SQLite | applications.status = sent | **Track replies** |

> Never presses Submit on a form with a required field empty: it goes back to review with that field as a question. A CAPTCHA or an emailed security code is always yours, in that window. LinkedIn and Indeed are never automated.

### Email applications

**Runs:** The model · `agent/llm.py · draft_email · agent/mailbox.py · send` · output schema: `EmailDraft`

**Input**

| Type | What | From |
|---|---|---|
| Text | the posting, post or article | **Rank the fit** |
| Markdown | storybook | **The storybook** |

**Output**

| Type | What | To |
|---|---|---|
| JSON | EmailDraft {subject, body} | **You review** |
| SMTP | sent from your mailbox after Approve | **Track replies** |

**Prompt** (`prompts.EMAIL`)

```text
Write a {kind} email from {first_name} to this company. Shape: one line on why this role, hinged on one concrete thing in the context; then what {first_name} can do and has done, as capabilities backed by experience (role, client, result), not a walkthrough of how a project works; then why that is an unusually close match for this role, said plainly; one light sentence of ambition (what they want to grow into here); end with a complete, polite sentence asking for a 20-minute conversation (e.g. 'Would you have 20 minutes in the next week or two to talk about the role?'), never a fragment like 'Worth 20 minutes?'. If the employer asked for specific write-ups (e.g. things you've built: the problem, how it works, what you'd change), answer every part they asked for, for each one, in connected sentences: what it is and the problem it solves, how it works, what the candidate would change. Never invent the change: if the documents don't give one, write [YOUR ANSWER: …]. Write for a reader who knows nothing about the candidate: introduce every project, company and tool in plain words (what it is and why it exists) before any detail, in full sentences with cause and effect; never open a line with a bare name, a link or a 'Problem:/How:' label. If the context is thin, write less rather than pad.
```

**Added when it applies** (`prompts.EMAIL_PROBLEM`)

```text
Propose, in 2-3 sentences, what the person would do about it, grounded in what they have actually done.
```

### Track replies

**Runs:** Code, no model · `agent/mailbox.py · fetch (IMAP) · agent/replies.py`

**Input**

| Type | What | From |
|---|---|---|
| IMAP | your mailbox, last 3 days, read-only | outside |
| SQLite | sent applications | **Submit** |

**Output**

| Type | What | To |
|---|---|---|
| SQLite | replies: confirmation · next step · interview · offer · rejected | outside |
| SQLite | Applied tab: submitted (with its confirmation email) · in progress · failed (with the reason) | outside |

> A receipt's 'if you are not selected' is not a rejection; newsletters and job alerts are never matched to an application.
