"""Every prompt the agent sends, in one place.

Each model call is: a system prefix (the same for every call, cached) + one task line from this file + the input for
that step. The prefix is built in agent/llm.py::_system from three files: docs/00-house-rules.md (the writing brief),
<profile>/preferences.yaml, and every file in <profile>/master (the storybook).

Placeholders in {braces} are filled at the call. Which step uses which prompt, what it reads and what it hands on:
agent/pipeline.py (rendered as docs/pipeline.md).
"""

SYSTEM = ("## House rules (docs/00-house-rules.md)\n…the one-page writing brief…\n\n"
          "## Preferences (preferences.yaml)\n…what to apply for, where, how often…\n\n"
          "## Master documents (the storybook)\n…every file in profile/master…\n\n"
          "## Task\n<one task line below>")

# 01 · your material → the storybook
STORYBOOK_ADD = ("Add what this material says about the person to their storybook. Use only facts the material states: never "
                 "guess numbers, titles, dates, degrees or tools. Skip anything the storybook already says. One fact per line, "
                 "résumé-ready, result first when the material gives one. In reference letters keep what the writer says the "
                 "person did, not the praise. Never turn a relative date ('last spring') into a year. A talk, award or press about a project is a line under that project. Don't add a degree as an entry "
                 "or a line: the résumé takes education from the standing answers. A file about someone else adds nothing: list it in "
                 "about_someone_else.")

STORYBOOK_STYLE = ("Rewrite the person's résumé lines in the style of the reference résumé, following their instruction. "
                   "Borrow structure, rhythm, verbs and how impact is framed. Keep every fact, number and name the same; add nothing. "
                   "Return only lines that actually change.")

INTAKE = ("Turn the raw material into storybook entries. Every line must be traceable to a file; "
          "list contradictions as conflicts; copy the person's own sentences verbatim into voice_samples.")

# 02 · postings → a ranked queue
RANK = ("Judge whether {first_name} is a credible candidate for this posting, as a strict recruiter in that field would. "
        "Map it to one role family below and say whether that family's seniority guard applies. Score every dimension below "
        "by its rubric, each with one sentence and words copied exactly from the posting as evidence; 0 when the posting says "
        "nothing about it. Work authorisation is settled, so it is never a blocker.\n\nDimensions:\n{dimensions}\n\nRole families: {roles}")

# 03 · a posting → the résumé and the answers
TAILOR = ("Build the one-page résumé for this posting through its lens in 06-roles.md, following the brief's résumé shape. "
          "Mark provenance honestly; 'new' items stay under {diy_max}. Where a piece of work has a URL in the master documents, "
          "set link_text and link.")

ALIGN = ("Align these résumé lines to the posting. List its 5-8 core requirements in its own words. Then reword each bullet and "
         "blurb in the posting's nouns where they truthfully fit, outcome first, and order bullets by the requirements. Reword, "
         "never add: facts are fixed, and a requirement the lines don't support stays uncovered, named in gaps. "
         "Keep entries, projects and their order.")

SUMMARY = ("Choose the parts of {first_name}'s résumé summary for this posting: the role in the posting's terms, the 2-3 fields "
           "and 3-5 skills from the record that this posting cares about most. Only what the record shows; code writes the sentence.")

REVISE = ("Revise this one-page résumé as the person asks. Change only what the note asks for; keep everything else as it is. "
          "Facts, numbers, titles and dates come from the master documents only: if the note asks for something they don't "
          "support, leave it out and say so in tailoring_notes. Keep provenance honest.")

REPAIR = "Rewrite the text to fix the listed problems. Same facts, same or shorter length."

ANSWERS = "Answer this application form. Anything only {first_name} can answer goes in needs_human with a short reason."

WHY_US = ("This is a cover letter or why-us answer: follow the brief's shape for them. Plain words and short sentences; open with "
          "why the candidate wants this role, close with the fit and their confidence stated outright. Draw the company's culture "
          "and stated direction from the posting and the mission notes; never describe their product. No 'I am writing'.")

EMAIL = ("Write a {kind} email from {first_name} to this company, following the brief's email shape. Write for a reader who "
         "knows nothing about {first_name}: say what each project is and why it exists before any detail. If the employer asks "
         "for write-ups, answer every part for each one in sentences; what {first_name} would change must come from the documents, "
         "else write [YOUR ANSWER: …]. "
         "If the context is thin, write less.")

EMAIL_PROBLEM = "Propose, in 2-3 sentences, what the person would do about it, grounded in what they have actually done."

COVER = ("Draft a cover letter and a 'Why {company}' answer for {first_name}, following the brief's cover-letter shape, from "
         "the storybook and what the posting or research says about the company. If the employer requires the candidate's own "
         "first draft, leave both empty and explain in needs_human.")

# 08 · your notes → proposed fixes
LEARN = ("Propose the smallest patches that would have prevented each problem. Prefer one example row in the brief over a new rule; "
         "keep the brief to one page. Use storybook_line only to reword an existing line with the same facts, quoting it exactly in 'before'. "
         "Use ban_phrase for a phrase that should never appear. Use preference for changes to what to apply for, where, or how often: "
         "replace one exact line of preferences.yaml in 'before' with the edited line in 'after'. Skip notes that need no change.")
