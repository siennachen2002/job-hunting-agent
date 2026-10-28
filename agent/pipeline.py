"""The agent, step by step: who does each step, with which model and prompt, what goes in and what comes out.

This is documentation that lives next to the code it describes. `python scripts/export_pipeline.py` renders it as
docs/pipeline.md and as the data behind the deck's appendix.

`runs` is one of:
  you     you do it in the dashboard
  model   a call to the model (JHA_MODEL)
  draft   a call to the draft model (JHA_DRAFT_MODEL), or the model when there is none
  code    plain code, no model
`prompt` (and `extra`, added when it applies) names a constant in agent/prompts.py; every model call also reads the
system prefix (prompts.SYSTEM). `schema` is the structured output the model returns. `short` is a shorter label for
the deck's flowchart.

`reads` and `gives` are typed: each entry is (type, name, node), where
  type   one of TYPES below, or a list of them when one entry carries several (["PDF", "DOCX"])
  name   the concrete file, table, schema or field: profile/master/*.md, jobs, JobScore, out/resumes/<name>.pdf
  node   the id of the step it comes from / goes to, a list of ids, or "" for outside the agent (you, the web, your mailbox)
"""

TYPES = ["PDF", "DOCX", "Audio", "Text", "Markdown", "YAML", "JSON", "SQLite", "PNG", "Web page", "API", "IMAP", "SMTP", "Click"]

NODES = [
    # ------------------------------------------------------------------ 01 · tell it everything
    dict(id="tell", step="01", name="Tell it everything", lane="you", runs="you", code="dashboard → Storybook chat (history kept per account)",
         reads=[(["PDF", "DOCX"], "old résumés, letters, papers", ""),
                ("Audio", "voice memos (M4A, MP3, WAV)", ""),
                ("Text", "what you type or say", "")],
         gives=[(["PDF", "DOCX", "Audio"], "the files (saved to profile/uploads/)", "storybook_add"),
                ("Text", "your note", "storybook_add"),
                ("Text", "everything you said or dropped, for the form answers", "standing"),
                ("PDF", "a résumé you like", "storybook_style")]),
    dict(id="storybook_add", step="01", name="Add to the storybook", lane="agent", runs="model", prompt="STORYBOOK_ADD", schema="Additions",
         code="agent/storybook.py · add_from",
         reads=[("Text", "each file's text (PDF and DOCX read, audio transcribed locally)", "tell"),
                ("Text", "your note", "tell"),
                ("Markdown", "profile/master/02-experience.md, 03-projects.md", "storybook")],
         gives=[("JSON", "Additions {file, entry, line, lenses, source}", "storybook"),
                ("Markdown", "new lines in profile/master/*.md", "storybook"),
                ("Markdown", "profile/.versions/<time>/ (Back undoes)", "")],
         note="A résumé that is about someone else adds nothing about you; on its own it goes to Learn a style instead."),
    dict(id="storybook_style", step="01", name="Learn a style", lane="agent", runs="model", prompt="STORYBOOK_STYLE", schema="Edits",
         code="agent/storybook.py · learn_from",
         reads=[("PDF", "reference résumé", "tell"),
                ("Text", "your instruction", "tell"),
                ("Markdown", "résumé lines, entry by entry", "storybook")],
         gives=[("JSON", "Edits {before, after, why}", "storybook"),
                ("Markdown", "reworded lines", "storybook")]),
    dict(id="intake", step="01", name="Intake draft (command line)", short="Intake draft", lane="agent", runs="draft", prompt="INTAKE",
         schema="Storybook", code="agent/intake.py · python -m agent.run intake",
         reads=[(["PDF", "DOCX", "Audio", "Text"], "inbox/*", "")],
         gives=[("Markdown", "profile/master/_intake-draft-<date>.md (you edit it)", "")]),
    dict(id="standing", step="01", name="Standing answers", lane="agent", runs="model", schema="Answers",
         code="agent/setup_answers.py · fill_from (in the background of the chat)",
         reads=[("Text", "what you said or dropped in the chat", "tell"),
                ("Click", "the form, to correct or finish it", "")],
         gives=[("YAML", "profile/standing.yaml", ["answers", "fill"]),
                ("Text", "the blanks left, named in the chat and marked on the form", "")],
         note="Filled from your words and files; you never have to type into the form. Required blanks are marked, never guessed."),
    dict(id="storybook", step="01", name="The storybook", lane="agent", runs="code", code="<profile>/master/*.md",
         reads=[("Markdown", "added lines", "storybook_add"),
                ("Markdown", "reworded lines", "storybook_style"),
                (["Markdown", "YAML"], "fixes you applied", "learn")],
         gives=[("Markdown", "profile/master/*.md + preferences.yaml + docs/00-house-rules.md, sent as the system prefix",
                 ["storybook_add", "rank", "tailor", "answers", "revise", "email", "cover"])],
         note="Files, not a step: every model call reads them, with the house rules and your preferences, as the system prefix."),
    # ------------------------------------------------------------------ 02 · find and rank
    dict(id="find", step="02", name="Find postings", lane="agent", runs="code", code="agent/sources/ (ats.py, boards.py, hn_hiring.py) · agent/run.py · discover, prefilter, find_jobs",
         reads=[("Click", "Find matching jobs (1-5), offered in the chat once the storybook is ready", ""),
                ("API", "Greenhouse · Lever · Ashby board APIs, read in parallel", ""),
                ("Web page", "Hacker News, Who is hiring", ""),
                ("Web page", "Built In NYC and Y Combinator's Work at a Startup: each role kept in its company's Greenhouse, Lever or Ashby version when there is one", ""),
                ("YAML", "profile/companies.yaml (watchlist, and the boards)", ""),
                ("YAML", "preferences.yaml (avoid_keywords)", "")],
         gives=[("SQLite", "jobs: company, title, location, url, description (talent pools skipped)", "rank")],
         note="You start it. The best-ranked jobs are then prepared one by one with no more clicks; each comes back as a Review button."),
    dict(id="rank", step="02", name="Rank the fit", lane="agent", runs="draft", prompt="RANK", schema="JobScore",
         code="agent/jev.py (Jev, TypeSafe) · agent/llm.py · score_jobs_claude_code → agent/scoring.py · finalize",
         reads=[("SQLite", "jobs (new)", "find"),
                ("API", "Jev P(fit) per posting, when TYPESAFE_API_KEY is set", ""),
                ("YAML", "profile/roles.yaml", ""),
                ("YAML", "preferences.yaml → scoring: the dimensions, their weights and rubrics", ""),
                ("Markdown", "storybook", "storybook")],
         gives=[("JSON", "JobScore {role_family, sector, dims [key, score 1-5 or 0, reason, evidence], guard, gaps, hard_blockers}", ["tailor", "verdict"]),
                ("SQLite", "jobs.score: the total, computed in code; score_json adds the model and the versions it was scored with", ["tailor", "verdict"]),
                ("SQLite", "jobs.status = queued | skipped", "tailor")],
         note="Jev rates every posting when its key is saved (Setup → API keys); without it Claude Code rates them, 8 per call, never an API key. "
              "The model scores each dimension and quotes the posting; code turns a quote not found in the posting into unknown, adds the "
              "dimensions up by weight (unknown counts as 3 of 5), and caps a seniority-guarded family at 50. Under 50 is never applied to."),
    dict(id="verdict", step="02", name="Good or Nope", lane="you", runs="you", code="dashboard → To do · agent/scoring.py · set_verdict",
         reads=[("JSON", "the dimension scores, reasons and quotes", "rank")],
         gives=[("SQLite", "verdicts: Good or Nope, the main reason, and the score as it was then", ""),
                ("Click", "Nope takes the job off To do; Prepare counts as Good", "tailor")],
         note="Your verdicts are what scoring is measured against: a change to the dimensions, weights, rubrics or prompt shows up as a new version on every score."),
    # ------------------------------------------------------------------ 03 · the résumé and the form
    dict(id="tailor", step="03", name="Write the résumé", lane="agent", runs="model", prompt="ALIGN", schema="Aligned",
         code="agent/assemble.py → agent/llm.py · align_resume → agent/resume/render.py",
         reads=[("SQLite", "the posting", "rank"),
                ("JSON", "JobScore", "rank"),
                ("Markdown", "storybook", "storybook")],
         gives=[("JSON", "ResumeContent", "check"),
                ("PDF", "out/resumes/<name>.pdf (one page)", "review"),
                ("PNG", "out/resumes/<name>.png (preview)", "review")],
         note="Picks the true lines for the role, then words them in the posting's nouns (never its prose) and orders them by its "
              "requirements; the two newest roles cover every core requirement. Facts never change: a new number or outcome keeps the original line. Two lines per bullet at most. "
              "The template: header links are words (Website · LinkedIn · GitHub), and every place, roles and schools alike, names its country. "
              "A two-to-three-sentence summary sells you for this role (prompt SUMMARY), from the page's own facts or not at all."),
    dict(id="check", step="03", name="Writing check", lane="agent", runs="model", prompt="REPAIR", schema="Repaired",
         code="agent/voicecheck.py (rules) · agent/llm.py · repair_text",
         reads=[("Text", "every bullet, answer and email", ["tailor", "answers", "email"]),
                ("YAML", "profile/learned_patterns.yaml (banned phrases)", "")],
         gives=[("Text", "the same facts, banned phrases rewritten", "tailor"),
                ("Text", "flags left for you", "review")],
         note="The rules are code (agent/voicecheck.py and the phrases you taught it): banned phrases, two lines per bullet, and in cover letters no colons, em dashes, small talk, empty contrasts or wh-clauses. The model only rewrites what they flag."),
    dict(id="answers", step="03", name="Answer the form", lane="agent", runs="model", prompt="ANSWERS", extra="WHY_US", schema="FormAnswers",
         code="agent/llm.py · answer_form · agent/mission.py",
         reads=[("Web page", "the form's fields, read live (label, type, required, options)", ""),
                ("SQLite", "the posting", "rank"),
                ("Text", "the company's mission, in its own words (agent/mission.py)", ""),
                ("YAML", "profile/standing.yaml", "standing"),
                ("YAML", "profile/saved-answers.yaml (questions you answered before)", "review")],
         gives=[("JSON", "FormAnswers {answers, needs_human}", "fill"),
                ("JSON", "needs_human: questions only you can answer", "review")],
         note="A question you answered before is answered again from Saved answers. Arbitration, certifications and export-control declarations always stay yours. Why-us questions add the WHY_US rule: the company's culture and the role, never a tour of their product."),
    dict(id="fill", step="03", name="Fill the form", lane="agent", runs="code", code="agent/apply/fill.py · Playwright · the agent's browser",
         reads=[("JSON", "FormAnswers", "answers"),
                ("YAML", "standing.yaml", "standing"),
                ("PDF", "the résumé", "tailor"),
                ("Web page", "the employer's form, in the agent's browser profile (data/browser)", "")],
         gives=[("PNG", "out/screens/app<id>.png (the filled form itself; nothing submitted)", "review")],
         note="Reads each radio group's own question, keeps every option, maps answers onto the form's wording (countries, opt-ins, the office nearest you). A required field or choice it can't fill becomes a question for you. "
              "Self-check (agent/doctor.py, on every Refresh): when this code changes, every waiting form is filled again on today's rules; failed submits come back to review; duplicate roles are withdrawn."),
    dict(id="cover", step="03", name="Cover letter", lane="agent", runs="model", prompt="WHY_US",
         schema="FormAnswers", code="agent/llm.py · answer_form (why-us and cover-letter questions) · agent/cover.py",
         reads=[("SQLite", "posting + research notes", "rank"),
                ("Markdown", "storybook", "storybook")],
         gives=[("Text", "the cover letter: the third document in review, beside the résumé and the form", "review")],
         note="Any 'why us', 'why this role' or cover-letter question. When the employer wants your own first draft, the card says so and waits. A [YOUR ANSWER] blank anywhere keeps Approve off."),
    # ------------------------------------------------------------------ 04 · you decide
    dict(id="review", step="04", name="You review", lane="you", runs="you", code="dashboard → Waiting for review",
         reads=[("PDF", "résumé", "tailor"),
                ("PNG", "filled form", "fill"),
                ("Text", "cover letter", "cover"),
                ("JSON", "questions for you", "answers"),
                ("Text", "checklist", "")],
         gives=[("Click", "Approve", ["submit", "email"]),
                ("Text", "Change this résumé: your note, typed or spoken", "revise"),
                ("Text", "Reject, with a reason (SQLite feedback)", "learn"),
                ("YAML", "your answers to questions for you, kept as Saved answers and filled on other applications at once", "answers")]),
    dict(id="revise", step="04", name="Revise the résumé", lane="agent", runs="model", prompt="REVISE", schema="ResumeContent",
         code="agent/run.py · revise · /api/applications/<id>/revise",
         reads=[("Text", "your note", "review"),
                ("JSON", "the current ResumeContent (applications.resume_json)", "tailor"),
                ("SQLite", "the posting", "rank"),
                ("Markdown", "storybook", "storybook")],
         gives=[("JSON", "ResumeContent", "review"),
                ("PDF", "the same file, re-rendered; a green dot when done", "review")],
         note="A branch: it changes this one application's résumé only. Asks the storybook can't support are left out and noted."),
    dict(id="learn", step="04", name="Learn from notes", lane="agent", runs="draft", prompt="LEARN", schema="Patches",
         code="agent/improve.py · suggest, outcomes → agent/learn.py · propose",
         reads=[("SQLite", "feedback: your notes", "review"),
                ("SQLite", "rejection reasons", "review"),
                ("SQLite", "verdicts: the Good posts that scored lowest and the Nope posts that scored highest", "verdict"),
                ("SQLite", "track record: changes applied and what they did, changes dismissed", ""),
                ("Markdown", "docs/00-house-rules.md", ""),
                ("YAML", "preferences.yaml", "")],
         gives=[("JSON", "Patches {kind, target, before, after, reason}", "storybook"),
                ("SQLite", "proposals (you apply or dismiss each, Activity or Storybook)", "storybook")],
         note="Code suggests first, from your verdicts, and checks each: weights only when they would rank your Good above your Nope "
              "at least 10 points more often; title words that are only ever in your Nope titles; watched companies that never "
              "give anything. The model then proposes writing and rubric changes. After you apply one, Activity shows what it did "
              "on the posts judged since, with the counts; nothing is called better or worse on fewer than 3."),
    # ------------------------------------------------------------------ 05 · out the door, and back
    dict(id="submit", step="05", name="Submit", lane="agent", runs="code",
         code="agent/run.py · submit_approved · agent/apply/fill.py · Playwright, visible",
         reads=[("Click", "approved applications only", "review"),
                ("JSON", "FormAnswers", "answers"),
                ("PDF", "résumé", "tailor"),
                ("Web page", "the employer's form", "")],
         gives=[("Web page", "the submitted application", ""),
                ("SQLite", "applications.status = sent", "track")],
         note="Never presses Submit on a form with a required field empty: it goes back to review with that field as a question. A CAPTCHA or an emailed security code is always yours, in that window. LinkedIn and Indeed are never automated."),
    dict(id="email", step="05", name="Email applications", lane="agent", runs="model", prompt="EMAIL", extra="EMAIL_PROBLEM", schema="EmailDraft",
         code="agent/llm.py · draft_email · agent/mailbox.py · send",
         reads=[("Text", "the posting, post or article", "rank"),
                ("Markdown", "storybook", "storybook")],
         gives=[("JSON", "EmailDraft {subject, body}", "review"),
                ("SMTP", "sent from your mailbox after Approve", "track")]),
    dict(id="track", step="05", name="Track replies", lane="agent", runs="code", code="agent/mailbox.py · fetch (IMAP) · agent/replies.py",
         reads=[("IMAP", "your mailbox, last 3 days, read-only", ""),
                ("SQLite", "sent applications", "submit")],
         gives=[("SQLite", "replies: confirmation · next step · interview · offer · rejected", ""),
                ("SQLite", "Applied tab: submitted (with its confirmation email) · in progress · failed (with the reason)", "")],
         note="A receipt's 'if you are not selected' is not a rejection; newsletters and job alerts are never matched to an application."),
]

RUNS = {"you": "You", "model": "The model", "draft": "The draft model (or the model)", "code": "Code, no model"}
STEPS = {"01": "Tell it everything", "02": "Find and rank", "03": "The résumé and the form", "04": "You decide", "05": "Out the door, and back"}
