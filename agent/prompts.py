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
        "Map it to one role family below; respect that family's seniority guard (cap at 50, action 'maybe'). "
        "Work authorisation is settled, so it is never a blocker. Role families: {roles}")

# 03 · a posting → the résumé and the answers
TAILOR = ("Build the one-page résumé content for this posting through the matching lens in 06-roles.md. "
          "First list the posting's core requirements; the two most recent roles must cover all of them on their own, "
          "with older roles and projects only reinforcing. Drop recent work that serves none of them. "
          "Mark each item's provenance honestly; 'new' items must stay under {diy_max}. "
          "Where a piece of work has a URL in the master documents, set link_text and link.")

REVISE = ("Revise this one-page résumé as the person asks. Change only what the note asks for; keep everything else as it is. "
          "Facts, numbers, titles and dates come from the master documents only: if the note asks for something they don't "
          "support, leave it out and say so in tailoring_notes. Keep provenance honest.")

REPAIR = "Rewrite the text to fix the listed problems. Same facts, same or shorter length."

ANSWERS = "Answer this application form. Anything only {first_name} can answer goes in needs_human with a short reason."

WHY_US = ("For a why-us question (why this company, what excites you about us): open with the company's mission in a sentence, "
          "in their words or close to them; then why it matters to the candidate as a person: character, habits, what they "
          "love doing (07-voice.md); experience last, one light touch at most. Never open with the candidate. "
          "A little American warmth and energy is welcome; hype words are not.")

EMAIL = ("Write a {kind} email from {first_name} to this company. Hinge it on one concrete thing in the context; "
         "if the context is thin, write less rather than pad.")

EMAIL_PROBLEM = "Propose, in 2-3 sentences, what the person would do about it, grounded in what they have actually done."

COVER = ("Draft a cover letter and a 'Why {company}' answer for {first_name}. Use only storybook facts "
         "and what the posting or research says about the company. If the employer requires the candidate's own first draft, "
         "leave both fields empty and explain in needs_human.")

# 08 · your notes → proposed fixes
LEARN = ("Propose the smallest patches that would have prevented each problem. Prefer one example row in the brief over a new rule; "
         "keep the brief to one page. Use storybook_line only to reword an existing line with the same facts, quoting it exactly in 'before'. "
         "Use ban_phrase for a phrase that should never appear. Use preference for changes to what to apply for, where, or how often: "
         "replace one exact line of preferences.yaml in 'before' with the edited line in 'after'. Skip notes that need no change.")
