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

ALIGN = ("Align this one-page résumé to the posting. First list the posting's 5-8 core requirements in its own words. Then rewrite "
         "every bullet and project blurb so a reader of this posting recognises their requirements: lead with the outcome or capability "
         "the posting asks for, use the posting's own nouns and requirement names where they truthfully describe the work (their word "
         "for the role, the activity, the user, the tool), but never its sentence rhythm or adjectives: plain verbs, the person's own "
         "voice, so this résumé doesn't read like everyone else's. Where a requirement names a domain or a length of experience, "
         "state it explicitly if the record supports it. Use any one posting term at most three times on the page. Order bullets inside each entry by how directly they answer the requirements. The two most "
         "recent roles must cover every core requirement between them. Facts are fixed: keep every number, employer, client, title, date "
         "and tool exactly as given; never add a tool, metric, client, result or responsibility that isn't already there, and never add "
         "what happened next or around it (deployed, adopted, drove adoption, rolled out, alongside a named person, a count in words); "
         "change the framing and the words, never the facts. If a "
         "requirement isn't supported, leave it uncovered and name it in gaps. Keep each bullet to one achievement in at most two lines "
         "(200 characters including spaces), "
         "opening verbs varied. Keep entries, projects and their order as given.")

REVISE = ("Revise this one-page résumé as the person asks. Change only what the note asks for; keep everything else as it is. "
          "Facts, numbers, titles and dates come from the master documents only: if the note asks for something they don't "
          "support, leave it out and say so in tailoring_notes. Keep provenance honest.")

REPAIR = "Rewrite the text to fix the listed problems. Same facts, same or shorter length."

ANSWERS = "Answer this application form. Anything only {first_name} can answer goes in needs_human with a short reason."

WHY_US = ("For a why-us question or cover letter (why this company, why this role, what excites you about us): open with the company's "
          "mission made concrete: one specific thing they built, decided or published (from the posting or the mission notes) and the "
          "candidate's honest reaction to it, never a paraphrased slogan. Then why it matters to the candidate as a person, shown "
          "through one short story, not adjectives: character, habits, what they love doing (07-voice.md); experience last, one light "
          "touch at most. Never open with the candidate or 'I am writing'. Swap test: delete any sentence that would still be true "
          "with another company's name in it. Don't summarize the résumé, don't list what the candidate wants from the job, "
          "use a number only if the master documents give it. Write it the way they'd say it across a table. "
          "Let real enthusiasm show: say plainly what genuinely excites the candidate about this work, in their own voice, with "
          "one vivid concrete detail. Balance it with professional judgment: one sharp observation about the company's problem or "
          "product in the field's own vocabulary, the way a practitioner would say it. Show passion, never claim it (no 'passionate'). "
          "Professional register: personality shows in what the candidate noticed, decided and built, and a well-placed joke is "
          "welcome; casual filler ('I love that', 'I'd love to', 'a lot of') is not. Every sentence must say something specific in "
          "precise words: no empty contrasts like 'as something you design for, not something that just happens'; name the "
          "concrete thing (the mechanism, the moment, the decision). No colons and no em dashes; write full sentences. "
          "Hype words are not welcome.")

EMAIL = ("Write a {kind} email from {first_name} to this company. Shape: one line on why this role, hinged on one concrete thing "
         "in the context; then what {first_name} can do and has done, as capabilities backed by experience (role, client, result), "
         "not a walkthrough of how a project works; then why that is an unusually close match for this role, said plainly; one light "
         "sentence of ambition (what they want to grow into here); end with a complete, polite sentence asking for a 20-minute conversation (e.g. 'Would you have 20 minutes in the next week or two to talk about the role?'), never a fragment like 'Worth 20 minutes?'. "
         "If the employer asked for specific write-ups (e.g. things you've built: the problem, how it works, what you'd change), "
         "answer every part they asked for, for each one, in connected sentences: what it is and the problem it solves, how it "
         "works, what the candidate would change. Never invent the change: if the documents don't give one, write [YOUR ANSWER: …]. "
         "Write for a reader who knows nothing about the candidate: introduce every project, company and tool in plain words "
         "(what it is and why it exists) before any detail, in full sentences with cause and effect; never open a line with a bare "
         "name, a link or a 'Problem:/How:' label. If the context is thin, write less rather than pad.")

EMAIL_PROBLEM = "Propose, in 2-3 sentences, what the person would do about it, grounded in what they have actually done."

COVER = ("Draft a cover letter and a 'Why {company}' answer for {first_name}, following the why-us rule: concrete mission first, "
         "one story, swap test on every sentence. Use only storybook facts "
         "and what the posting or research says about the company. If the employer requires the candidate's own first draft, "
         "leave both fields empty and explain in needs_human.")

# 08 · your notes → proposed fixes
LEARN = ("Propose the smallest patches that would have prevented each problem. Prefer one example row in the brief over a new rule; "
         "keep the brief to one page. Use storybook_line only to reword an existing line with the same facts, quoting it exactly in 'before'. "
         "Use ban_phrase for a phrase that should never appear. Use preference for changes to what to apply for, where, or how often: "
         "replace one exact line of preferences.yaml in 'before' with the edited line in 'after'. Skip notes that need no change.")
