"""Form answers decided in code, on made-up standing answers: no model, no browser, no network, nothing of yours read.

    python3 tests/rules_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import answer_bank, config, replies, setup_answers  # noqa: E402
from agent.apply import identity, standing  # noqa: E402

SA = {"legal_first": "Ada", "legal_last": "Lovelace", "email": "ada@example.com", "phone": "555-0100",
      "website": "https://example.com", "city": "Brooklyn, NY", "authorized_in": "United States",
      "sponsorship_now": "Yes", "sponsorship_future": "Yes", "onsite": "Hybrid"}
setup_answers.load = lambda: dict(SA)
config.preferences = lambda: {}
config.profile = lambda: {}


def check(name, got, want):
    if got != want:
        raise SystemExit(f"FAIL {name}: got {got!r}, want {want!r}")


ask = standing.standing_answer
# sponsorship: "without sponsorship" asks the opposite of "do you need sponsorship"
check("needs sponsorship", ask("Do you require visa sponsorship?"), "Yes")
check("authorized without sponsorship", ask("Are you authorized to work in the US without sponsorship?"), "No")
check("without requiring sponsorship", ask("Are you legally authorized to work in the United States without requiring visa sponsorship?"), "No")
check("sponsor you", ask("Will you require Acme to sponsor you for a work visa?"), "Yes")
# an answer must fit the question's shape
check("yes/no question gets no link", ask("Are you comfortable completing a take-home design exercise?"), None)
check("how many gets no yes", ask("How many days per week can you work from the office?"), None)
check("portfolio link", ask("Portfolio URL"), "https://example.com")
check("current location", ask("What is your current location?"), "Brooklyn, NY")
# name and contact fields, not questions about them
check("first name", identity.identity_answer("First name"), "Ada")
check("email field", identity.identity_answer("Email address"), "ada@example.com")
check("question about emails", identity.identity_answer("Would you like to receive emails about future roles?"), None)
check("school name", identity.identity_answer("University name"), None)
check("pronounce", identity.identity_answer("How do you pronounce your name?"), None)

# saved answers: a checkbox's raw "on" is never reused; "located in" counts only for the same place
bank = [{"question": "Do you have unrestricted work authorization in the United States?", "answer": "on", "topic": None, "scope": "any"},
        {"question": "Are you currently located in the US?", "answer": "Yes", "topic": "located", "scope": "any"}]
answer_bank.load = lambda: bank
check("raw checkbox value", answer_bank.lookup("Do you have unrestricted work authorization in the United States?", "Acme"), None)
check("same place", answer_bank.lookup("Are you located in the US?", "Acme"), "Yes")
check("other place", answer_bank.lookup("Are you currently located in the United Kingdom?", "Acme"), None)

# replies: the company part of a domain, never a generic one like careers.
apps = [{"id": 1, "company": "Roblox", "title": "Designer", "domains": ["careers.roblox.com"], "sent_at": ""},
        {"id": 2, "company": "Figma", "title": "Designer", "domains": ["figma.com"], "sent_at": ""}]
check("generic careers sender", replies.match({"sender": "Stripe Careers <careers@stripe.com>", "subject": "Update", "body": None}, apps), None)
check("company domain", (replies.match({"sender": "Roblox <no-reply@roblox.com>", "subject": "Your application"}, apps) or {}).get("id"), 1)
check("company named", (replies.match({"sender": "no-reply@us.greenhouse-mail.io", "subject": "Thank you for applying to Figma",
                                       "body": "Thanks for applying to Figma"}, apps) or {}).get("id"), 2)

print("rules: all checks pass")
