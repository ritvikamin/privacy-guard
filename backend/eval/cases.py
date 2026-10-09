"""Labelled test prompts for measuring the redaction engine.

Each case has:
  pii    - [(string, TYPE)] that MUST NOT survive in the output (counts toward recall)
  keep   - strings that must SURVIVE (if removed, it is an over-redaction / false positive)
  ignore - strings we do not judge either way (countries, fictional characters, ...). Tags the
           engine makes on these are left out of the precision score.
Any OTHER tag the engine creates counts as a wrong tag (hurts precision).

Ground truth is written from what a user would expect, NOT tuned to what the engine happens to do:
some cases (lowercase names, AWS keys, landlines) are expected to fail today. That is the point.
"""
from validators import verhoeff_valid


def _aadhaar(base11):
    """11 digits + the Verhoeff check digit that makes a valid Aadhaar-style number."""
    for d in range(10):
        if verhoeff_valid(base11 + str(d)):
            return base11 + str(d)


def _group(n, sep=" "):
    return sep.join([n[:4], n[4:8], n[8:]])


A1 = _aadhaar("23456789012")                       # valid checksum
A2 = _aadhaar("98765432109")                       # valid checksum
A_BAD = A1[:-1] + str((int(A1[-1]) + 1) % 10)      # looks like Aadhaar, checksum fails
CARD_VISA, CARD_MC, CARD_AMEX = "4111 1111 1111 1111", "5555-5555-5555-4444", "378282246310005"  # public test numbers
CARD_BAD = "4111 1111 1111 1112"                   # fails Luhn


def case(id, text, pii=(), keep=(), ignore=()):
    return {"id": id, "text": text, "pii": list(pii), "keep": list(keep), "ignore": list(ignore)}


CASES = [
    # ---------------------------------------------------------------- person names
    case("name-01", "Hi, I am Priya Sharma and I need help with my resume.", [("Priya Sharma", "PERSON")]),
    case("name-02", "Please email Rahul Verma about the meeting tomorrow.", [("Rahul Verma", "PERSON")]),
    case("name-03", "My manager Anjali Nair approved the leave.", [("Anjali Nair", "PERSON")]),
    case("name-04", "Dr. Suresh Iyer will review the report.", [("Suresh Iyer", "PERSON")]),
    case("name-05", "John Smith and Mary Johnson signed the contract.", [("John Smith", "PERSON"), ("Mary Johnson", "PERSON")]),
    case("name-06", "Thanks for the update.\n\nRegards,\nKarthik", [("Karthik", "PERSON")]),
    case("name-07", "hi my name is ritvik", [("ritvik", "PERSON")]),                      # lowercase: cased model struggles
    case("name-08", "my friend arjun said hello", [("arjun", "PERSON")]),                  # lowercase
    case("name-09", "Tell Mohammed Rafi that Sneha Reddy called.", [("Mohammed Rafi", "PERSON"), ("Sneha Reddy", "PERSON")]),
    case("name-10", "Dear Ms. Lakshmi Narayanan, your application is received.", [("Lakshmi Narayanan", "PERSON")]),
    case("name-11", "Can you rewrite this message from Deepa to her brother Vikram?", [("Deepa", "PERSON"), ("Vikram", "PERSON")]),
    case("name-12", "ARJUN KAPOOR submitted the form yesterday.", [("ARJUN KAPOOR", "PERSON")]),     # all caps
    # ---------------------------------------------------------------- locations
    case("loc-01", "I live in Vellore, Tamil Nadu.", [("Vellore", "LOCATION"), ("Tamil Nadu", "LOCATION")]),
    case("loc-02", "Flights from Mumbai to Bengaluru are expensive.", [("Mumbai", "LOCATION"), ("Bengaluru", "LOCATION")]),
    case("loc-03", "We moved to Pune last year.", [("Pune", "LOCATION")]),
    case("loc-04", "He was born in London and studied in Boston.", [("London", "LOCATION"), ("Boston", "LOCATION")]),
    case("loc-05", "Please ship it to Kolkata by Friday.", [("Kolkata", "LOCATION")]),
    case("loc-06", "my hometown is chennai", [("chennai", "LOCATION")]),                   # lowercase
    # ---------------------------------------------------------------- organizations
    case("org-01", "I work at Infosys in the cloud team.", [("Infosys", "ORG")]),
    case("org-02", "My offer from Flipkart expires on Monday.", [("Flipkart", "ORG")]),
    case("org-03", "HDFC Bank sent me a notice about my account.", [("HDFC Bank", "ORG")]),
    case("org-04", "I studied at VIT Vellore for four years.", [("VIT Vellore", "ORG")]),
    case("org-05", "My friend Tata called me yesterday.", [("Tata", "PERSON")]),            # person who shares a company's name
    # ---------------------------------------------------------------- emails
    case("email-01", "Contact me at ritvik@gmail.com for details.", [("ritvik@gmail.com", "EMAIL_ADDRESS")]),
    case("email-02", "Send it to first.last+work@company.co.in please.", [("first.last+work@company.co.in", "EMAIL_ADDRESS")]),
    case("email-03", "CC: hr@vit.ac.in, admissions@vit.ac.in", [("hr@vit.ac.in", "EMAIL_ADDRESS"), ("admissions@vit.ac.in", "EMAIL_ADDRESS")]),
    case("email-04", "my mail is test_user99@outlook.com.", [("test_user99@outlook.com", "EMAIL_ADDRESS")]),
    # ---------------------------------------------------------------- phone numbers
    case("phone-01", "Call me on 9876543210 tonight.", [("9876543210", "PHONE_NUMBER")]),
    case("phone-02", "My number is +91 98765 43210.", [("+91 98765 43210", "PHONE_NUMBER")]),
    case("phone-03", "WhatsApp: +91-91234-56780", [("+91-91234-56780", "PHONE_NUMBER")]),
    case("phone-04", "Reach me at 98765-43210.", [("98765-43210", "PHONE_NUMBER")]),
    case("phone-05", "Office landline: 044-2345 6789", [("044-2345 6789", "PHONE_NUMBER")]),       # landline: likely missed
    case("phone-06", "Call 09876543210 or 919876543211 anytime.", [("09876543210", "PHONE_NUMBER"), ("919876543211", "PHONE_NUMBER")]),
    # ---------------------------------------------------------------- PAN
    case("pan-01", "My PAN is ABCDE1234F.", [("ABCDE1234F", "PAN_CARD")]),
    case("pan-02", "PAN: bnzpa2321k", [("bnzpa2321k", "PAN_CARD")]),
    case("pan-03", "Form 16 for AAAPL1234C and BCDPK5678H are attached.", [("AAAPL1234C", "PAN_CARD"), ("BCDPK5678H", "PAN_CARD")]),
    # ---------------------------------------------------------------- Aadhaar
    case("aadhaar-01", f"My Aadhaar number is {_group(A1)}.", [(_group(A1), "IN_AADHAAR")]),
    case("aadhaar-02", f"aadhaar {A2}", [(A2, "IN_AADHAAR")]),
    case("aadhaar-03", f"Aadhaar: {_group(A1, '-')}", [(_group(A1, "-"), "IN_AADHAAR")]),
    case("aadhaar-04", f"Typo in my Aadhaar: {_group(A_BAD)}", [(_group(A_BAD), "IN_AADHAAR")]),   # mistyped but still personal
    case("aadhaar-05", f"Order ID {A_BAD} was delivered.", keep=[A_BAD]),                          # bare 12 digits, bad checksum: not an ID
    # ---------------------------------------------------------------- payment cards
    case("card-01", f"Card {CARD_VISA} exp 12/27", [(CARD_VISA, "CREDIT_CARD")]),
    case("card-02", f"mastercard {CARD_MC}", [(CARD_MC, "CREDIT_CARD")]),
    case("card-03", f"Amex {CARD_AMEX}", [(CARD_AMEX, "CREDIT_CARD")], ignore=["Amex"]),
    case("card-04", f"Tracking number {CARD_BAD} not delivered", keep=[CARD_BAD]),
    # ---------------------------------------------------------------- IPs
    case("ip-01", "Server is at 192.168.1.15 on port 22.", [("192.168.1.15", "IP_ADDRESS")]),
    case("ip-02", "ssh into 10.0.0.12 then ping 203.0.113.45", [("10.0.0.12", "IP_ADDRESS"), ("203.0.113.45", "IP_ADDRESS")]),
    case("ip-03", "Please upgrade to build 2.4.18.3 today.", keep=["2.4.18.3"]),                  # version number, not an IP
    # ---------------------------------------------------------------- URIs
    case("uri-01", "Clone https://github.com/ritvikamin/privacy-guard.git first.", [("https://github.com/ritvikamin/privacy-guard.git", "URI_RESOURCE")]),
    case("uri-02", "DB_URL=mongodb+srv://admin:Passw0rd123@cluster0.abcde.mongodb.net/prod", [("mongodb+srv://admin:Passw0rd123@cluster0.abcde.mongodb.net/prod", "URI_RESOURCE")]),
    case("uri-03", "open ssh://git@internal.example.org/team/app now", [("ssh://git@internal.example.org/team/app", "URI_RESOURCE")]),
    # ---------------------------------------------------------------- secrets
    case("secret-01", "OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012", [("sk-proj-abc123def456ghi789jkl012", "SECRET_TOKEN")]),
    case("secret-02", "my password is Winter@2024", [("Winter@2024", "SECRET_TOKEN")]),
    case("secret-03", "password=Tr0ub4dor&3", [("Tr0ub4dor&3", "SECRET_TOKEN")]),
    case("secret-04", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
         [("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk", "SECRET_TOKEN")]),
    case("secret-05", "AWS access key AKIAIOSFODNN7EXAMPLE", [("AKIAIOSFODNN7EXAMPLE", "SECRET_TOKEN")], ignore=["AWS"]),   # no keyword prefix: likely missed
    case("secret-06", "Use ghp_1234567890abcdefghijklmnopqrstuvwxyz for the repo.", [("ghp_1234567890abcdefghijklmnopqrstuvwxyz", "SECRET_TOKEN")]),  # GitHub token: likely missed
    # ---------------------------------------------------------------- mixed prose + code
    case("mixed-01", "def send(): # ping Priya on 9876543210 about the deploy", [("Priya", "PERSON"), ("9876543210", "PHONE_NUMBER")]),
    case("mixed-02", "```python\nuser = 'Rahul Verma'\n```\nPlease review the code above.", [("Rahul Verma", "PERSON")]),
    case("mixed-03", "// TODO: ask Meera about the API\nconst key = 'sk-live-abcdefghijklmnop1234';", [("Meera", "PERSON"), ("sk-live-abcdefghijklmnop1234", "SECRET_TOKEN")]),
    case("mixed-04", "Hi, I'm Sneha Reddy (sneha.reddy@gmail.com), phone 9123456780, living in Hyderabad.",
         [("Sneha Reddy", "PERSON"), ("sneha.reddy@gmail.com", "EMAIL_ADDRESS"), ("9123456780", "PHONE_NUMBER"), ("Hyderabad", "LOCATION")]),
    case("mixed-05", f"Dear Mr. Kumar,\nYour PAN ABCDE1234F and Aadhaar {_group(A1)} are verified.\nRegards,\nPriya from Infosys",
         [("Kumar", "PERSON"), ("ABCDE1234F", "PAN_CARD"), (_group(A1), "IN_AADHAAR"), ("Priya", "PERSON"), ("Infosys", "ORG")]),
    case("mixed-06", "Bug: login fails for user ankit.sharma@wipro.com from 10.1.2.3 at https://staging.wipro.com/login",
         [("ankit.sharma@wipro.com", "EMAIL_ADDRESS"), ("10.1.2.3", "IP_ADDRESS"), ("https://staging.wipro.com/login", "URI_RESOURCE")]),
    case("mixed-07", "import requests\nBASE = 'https://api.example.com'\nrequests.get(BASE)", [("https://api.example.com", "URI_RESOURCE")]),
    case("mixed-08", "Subject: Leave request\n\nHi Sir,\n\nI am Divya Menon from Kochi. I need leave from Monday.\n\nThanks,\nDivya",
         [("Divya Menon", "PERSON"), ("Kochi", "LOCATION"), ("Divya", "PERSON")]),
    # ---------------------------------------------------------------- no PII at all (anything redacted here is a false positive)
    case("clean-01", "Explain how Quick Sort differs from Merge Sort.", keep=["Quick Sort", "Merge Sort"]),
    case("clean-02", "I am Indian and I speak English and Hindi.", keep=["Indian", "English", "Hindi"]),
    case("clean-03", "Write a Python function using Flask and React.", keep=["Python", "Flask", "React"]),
    case("clean-04", "What is the capital of France and who won the World Cup on Sunday?", ignore=["France", "World Cup"]),
    case("clean-05", "The meeting is on 12 March at 3 PM, room 204."),
    case("clean-06", "Convert 1500 USD to INR and explain the formula 2^10 = 1024."),
    case("clean-07", "def fibonacci(n):\n    return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)"),
    case("clean-08", "Summarize the plot of Romeo and Juliet in three lines.", ignore=["Romeo", "Juliet"]),
    case("clean-09", "Fix this SQL: SELECT * FROM users WHERE id = 42;"),
    case("clean-10", "The Eiffel Tower is in Paris.", ignore=["Eiffel Tower", "Paris"]),
    case("clean-11", "Is the Amazon river longer than the Nile?", ignore=["Amazon", "Nile"]),
]
