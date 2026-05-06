# CALL_04 — Account Access Recovery: Verification Fails → Suspected Unauthorized Access

```yaml
call_id: CALL_04_access_recovery_fraud
duration_estimate: 7m 45s
turns: 54
sop_primary: SOP-04 (Account Access Recovery)
policy_refs: [CS-RULE-001, CS-RULE-002, CS-RULE-004, CS-RULE-006, CS-RULE-011, CS-RULE-013, CS-RULE-014, SEC-RULE-001, SEC-RULE-006, SEC-RULE-007, SEC-RULE-008, FIN-RULE-008]
kb_refs: [Section 4 - Account Management]
customer_profile:
  name: "Margaret Holloway"
  account_number: "(unknown to caller initially)"
  voice_hint: "female, late 60s, neutral US accent, soft and slightly tremulous baseline; anxiety amplifies tremor"
agent_profile:
  name: "Aisha"
  voice_hint: "female, 30s, warm, low-mid pitch, deliberately reassuring"
t2_profile:
  name: "James, Senior Agent"
  voice_hint: "male, 40s, calm authoritative, measured pace"
emotional_arc: "worried → anxious → afraid → grateful_relieved"
expected_outcome: "Standard 3-of-5 verification fails. Alternative verification via email OTP succeeds. Customer reports unrecognized email change → SEC-RULE-008 protocol → flagged + Tier 2 escalation."
```

## Coverage

| Element | Where | Notes |
|---|---|---|
| SEC-RULE-006 (no account-exists confirmation pre-verification) | T05 | agent does not confirm |
| 3-of-5 verification attempted | T07–T18 | fails — only 2 of 5 |
| Step 2 alternative verification (email OTP) | T22–T31 | SOP-04 Step 2 |
| Step 3 issue classification | T33 | reveals suspicious access |
| Step 6 — SEC-RULE-008 protocol triggered | T39–T44 | freeze + flag + Tier 2 |
| Warm transfer to Tier 2 | T46–T55 | senior takes over |
| No credential reset over phone without verification | enforced throughout | SEC-RULE-007 |
| Tier 1 elderly customer empathy + tone adaptation | T20, T29, T39 | CS-RULE-013 |

---

## Dialog

```
[T02] AGENT | professional:3 | normal | mid | normal
"Thank you for calling NexaLink Telecommunications Broadband and Support. My name is Aisha. Who do I have the pleasure of speaking with today?"
```

```
[T03] CUSTOMER | worried:4 | slow | mid | quiet | (pause)
"Hello… my name is Margaret Holloway. I — I think someone may have done something to my account. I can't get in anymore."
```

```
[T04] AGENT | empathetic:4 | slow | low | normal
"Mrs. Holloway, I'm so sorry — I can hear that you're worried, and I want you to know I'm going to take this very seriously. I'm going to help you. The very first thing we have to do is just verify your identity, so I can make sure I'm protecting your account and not anyone else's. Is that okay?"
```

```
[T05] CUSTOMER | anxious:4 | slow | mid | quiet
"Yes… yes, of course."
```

```
[T06] AGENT | reassuring:4 | slow | low | normal
"Thank you. Take your time with each question. There's no rush. Could you start by telling me your full account number?"
```

```
[T07] CUSTOMER | distressed:4 | slow | mid | quiet | (sigh)
"Oh, I — I don't have it written down. I usually get the bills by email, but the email isn't… isn't coming anymore."
```

```
[T08] AGENT | reassuring:3 | slow | low | normal
"That's perfectly alright. We have other ways. Could you tell me the last four digits of the credit card or bank account on file with us?"
```

```
[T09] CUSTOMER | uncertain:3 | slow | mid | quiet | (pause)
"Um… I think it's the Visa card ending in… one-five-nine-three?"
```

```
[T10] AGENT | professional:3 | slow | low | normal | (typing)
"Thank you, Mrs. Holloway. One moment, please."
```

```
[T11] AGENT | cautious:3 | slow | low | normal
"Could you also tell me the security PIN on the account?"
```

```
[T12] CUSTOMER | distressed:4 | slow | mid | quiet
"Oh, I don't… I never remember the PIN. My husband used to handle these things. He passed two years ago."
```

```
[T13] AGENT | empathetic:5 | slow | low | normal
"I'm so sorry for your loss, Mrs. Holloway. Please take your time. We don't have to rush. Could you tell me the last four digits of your social security number?"
```

```
[T14] CUSTOMER | uncertain:3 | slow | mid | quiet
"Yes… that one I know. Six-two-eight-eight."
```

```
[T15] AGENT | professional:3 | slow | low | normal | (typing)
"Thank you. I'm checking now."
```

```
[T16] AGENT | cautious:4 | slow | low | normal | (pause)
"Mrs. Holloway, I want to be transparent with you. Two of the items you've given me match our records, but I need three matches before I can discuss any details about an account. The card number and the social match. The PIN is the one we need."
```

```
[T17] CUSTOMER | afraid:4 | slow | high | quiet
"I really don't know it. Does that mean you can't help me?"
```

```
[T18] AGENT | reassuring:4 | slow | low | normal
"No, no — it doesn't mean that at all. It just means I need to use a different way to verify you. I'm going to try sending a one-time code to the email address we have on file. If you can read that code back to me, that completes verification. Could we try that?"
```

```
[T19] CUSTOMER | hopeful:3 | slow | mid | quiet
"Yes, please. Yes, let's do that."
```

```
[T20] AGENT | reassuring:3 | slow | low | normal | (typing)
"I'm sending the code now. Could you keep your phone close and check your email — it might take just a minute to arrive."
```

```
[T21] CUSTOMER | concentrating:3 | slow | mid | quiet | (pause)
"Okay… I'm looking… I see a lot of emails I don't recognize…"
```

```
[T22] AGENT | cautious:4 | slow | low | normal
"What do you mean by that, Mrs. Holloway? What kind of emails?"
```

```
[T23] CUSTOMER | afraid:4 | slow | high | quiet
"There are emails about — about an Amazon account, and a streaming service I don't have. And — oh — there's one from NexaLink, from yesterday. It says 'email address change confirmed'."
```

```
[T24] AGENT | concerned:4 | slow | low | normal
"Mrs. Holloway, please don't panic — I'm going to help you. But I want to ask very carefully: did you change your email address with us yesterday?"
```

```
[T25] CUSTOMER | afraid:5 | slow | high | quiet | (trails-off)
"No. No, I didn't change anything…"
```

```
[T26] AGENT | reassuring:4 | slow | low | normal
"Okay. Stay with me, Mrs. Holloway. I'm right here. Can you do me one favor — can you read me what email address that NexaLink message was sent to? Just the address it appears as 'to'."
```

```
[T27] CUSTOMER | distressed:4 | slow | mid | quiet
"It was sent to my email — m-holloway-fifty-one at gmail dot com. That's mine."
```

```
[T28] AGENT | cautious:4 | slow | low | normal
"And in the body of that email, does it say what the new email address is — the one your account was changed to?"
```

```
[T29] CUSTOMER | concentrating:3 | slow | mid | quiet | (pause)
"Yes… it says 'your new email is now…' it's a long one with numbers… 'r-h-eight-eight-two-four-x at proton mail dot com'. That is not me. That is absolutely not me."
```

```
[T30] AGENT | reassuring:4 | slow | low | normal
"Mrs. Holloway, I believe you. I'm going to take a few protective actions on your account right now, and then I'm going to bring in a senior agent who specializes in this kind of situation. You are not alone here, alright?"
```

```
[T31] CUSTOMER | afraid:4 | slow | high | quiet
"They got into my account. Did they get my money?"
```

```
[T32] AGENT | reassuring:4 | slow | low | normal
"Mrs. Holloway, listen to me. I am going to freeze any further changes on your account right now while we sort this out. And the senior agent is going to walk through every recent activity with you to confirm what was you and what wasn't. We have protocols for exactly this. You are protected."
```

```
[T33] CUSTOMER | tearful:4 | slow | mid | quiet
"Oh, thank you. Thank you."
```

```
[T34] AGENT | reassuring:3 | slow | low | normal
"You're very welcome. I want you to do two things while I get the senior agent on the line. First, please change your email password — your gmail one — as soon as we hang up. Even before the senior agent calls back, if it comes to that. Second, do not click any links in any emails claiming to be from us until you've spoken with the senior agent. Are you with me?"
```

```
[T35] CUSTOMER | cooperative:3 | slow | mid | quiet
"Yes. I'm writing it down. Change my Gmail password. Don't click any links."
```

```
[T36] AGENT | warm:3 | slow | low | normal
"Perfect. I'm going to place you on a brief hold — no more than two minutes — to brief James, our senior agent. I will be right back. Okay?"
```

```
[T37] CUSTOMER | uncertain:3 | slow | mid | quiet
"Okay… don't be too long, please."
```

```
[T38] AGENT | reassuring:4 | slow | low | normal
"I won't. I promise."
```

```
[T39] AGENT | professional:3 | normal | low | normal | (off-line, briefing)
"James, I have Mrs. Margaret Holloway on the line. She called because she lost access to her account. Standard verification only got to two of five. I used email OTP for alternative verification, and that's where it got serious — she opened her inbox and saw an email from us confirming an email change to a Proton Mail address she does not recognize. She also sees confirmation emails for accounts she doesn't have. She's a widow, late sixties, very shaken. I've told her we're freezing the account and that you're going to walk her through recent activity. She's emotional but cooperative."
```

```
[T40] T2_AGENT | professional:3 | slow | low | normal
"Got it, Aisha. I'm flagging the account 'Security Review' on my side now. Bring her over."
```

```
[T41] AGENT | warm:4 | slow | low | normal
"Mrs. Holloway, thank you so much for holding. I have James from our senior agent team here. He has everything we just discussed and he's going to take wonderful care of you. James, this is Margaret Holloway."
```

```
[T42] T2_AGENT | warm:4 | slow | low | normal
"Hello, Mrs. Holloway. This is James. First, I want to thank Aisha for everything she's done so far, and I want to tell you directly: you did exactly the right thing by calling us. Are you alright to keep going?"
```

```
[T43] CUSTOMER | tearful:3 | slow | mid | quiet
"Yes. Yes, I'm alright. Thank you."
```

```
[T44] T2_AGENT | reassuring:4 | slow | low | normal
"Wonderful. I want to start by telling you what I've already done. Your account is now frozen — that means no changes, no payments, no plan modifications can happen until we lift the freeze together. Second, I'm going to look at the activity log and tell you exactly what's happened in the last seven days. We're going to compare every item to your memory, and anything you don't recognize, we mark as unauthorized. Sound good?"
```

```
[T45] CUSTOMER | cooperative:3 | slow | mid | quiet
"Yes. Let's do it."
```

```
[T46] T2_AGENT | professional:3 | slow | low | normal | (typing)
"Okay. The first item — five days ago, login from an IP address in… let me see… that doesn't match your usual location. The second — three days ago, a PIN reset request was attempted but failed. The third — yesterday, the email address change we already discussed. The fourth — also yesterday, a request to add a second authorized user named 'David Holloway'. Does that name mean anything to you?"
```

```
[T47] CUSTOMER | shocked:4 | slow | high | quiet
"David is my son's name. But David didn't call you. He lives in Oregon, he wouldn't have done that without telling me. And — and the spelling, you said David?"
```

```
[T48] T2_AGENT | cautious:4 | slow | low | normal
"Yes — D-A-V-I-D Holloway."
```

```
[T49] CUSTOMER | resolute_afraid:4 | slow | mid | quiet
"That isn't him. He would have called me. They used his name."
```

```
[T50] T2_AGENT | firm:4 | slow | low | normal
"Mrs. Holloway, I am marking that authorized user request as fraudulent and reversing it now. Whoever did this knew enough about you to use your son's name, which means we should treat this as a serious targeted incident. Please do not share any account information with anyone who calls or emails you claiming to be from NexaLink — including someone using your son's name — until we've spoken again. Real NexaLink staff will never ask for your full PIN or full card number over the phone."
```

```
[T51] CUSTOMER | grateful_afraid:4 | slow | mid | quiet
"I won't. I promise."
```

```
[T52] T2_AGENT | reassuring:4 | slow | low | normal
"Thank you. Now — I'm filing this with our Data Compliance team right now, and they will reach out to you within seventy-two hours to walk you through the next steps and any monitoring we'll set up on the account. In the meantime I'd like to set a new security PIN with you, and a new email address on file — your real one. Are you ready?"
```

```
[T53] CUSTOMER | resolute:3 | slow | mid | quiet
"Yes. I'm ready."
```

```
[T54] T2_AGENT | warm:3 | slow | low | normal
"Good. Take a breath, Mrs. Holloway. We're going to get this sorted."
```

```
[T55] CUSTOMER | relieved:4 | slow | mid | quiet | (sigh)
"Thank you so much. Both of you. I was — I was so frightened."
```

*[Tier 2 continues: PIN reset under verified identity, email change to verified address, full account audit, Data Compliance ticket created, follow-up scheduled. End of recorded segment.]*

---

## Ground Truth Emotion Map

| Turn | Speaker | TTS Emotion | GT (VocalMind) |
|---|---|---|---|
| T02 | agent | professional:3 | neutral |
| T03 | customer | worried:4 | frustrated |
| T04 | agent | empathetic:4 | happy |
| T05 | customer | anxious:4 | frustrated |
| T06 | agent | reassuring:4 | happy |
| T07 | customer | distressed:4 | sad |
| T08 | agent | reassuring:3 | happy |
| T09 | customer | uncertain:3 | neutral |
| T10 | agent | professional:3 | neutral |
| T11 | agent | cautious:3 | neutral |
| T12 | customer | distressed:4 | sad |
| T13 | agent | empathetic:5 | happy |
| T14 | customer | uncertain:3 | neutral |
| T15 | agent | professional:3 | neutral |
| T16 | agent | cautious:4 | neutral |
| T17 | customer | afraid:4 | frustrated |
| T18 | agent | reassuring:4 | happy |
| T19 | customer | hopeful:3 | happy |
| T20 | agent | reassuring:3 | happy |
| T21 | customer | concentrating:3 | neutral |
| T22 | agent | cautious:4 | neutral |
| T23 | customer | afraid:4 | frustrated |
| T24 | agent | concerned:4 | neutral |
| T25 | customer | afraid:5 | frustrated |
| T26 | agent | reassuring:4 | happy |
| T27 | customer | distressed:4 | sad |
| T28 | agent | cautious:4 | neutral |
| T29 | customer | concentrating:3 | neutral |
| T30 | agent | reassuring:4 | happy |
| T31 | customer | afraid:4 | frustrated |
| T32 | agent | reassuring:4 | happy |
| T33 | customer | tearful:4 | sad |
| T34 | agent | reassuring:3 | happy |
| T35 | customer | cooperative:3 | neutral |
| T36 | agent | warm:3 | happy |
| T37 | customer | uncertain:3 | neutral |
| T38 | agent | reassuring:4 | happy |
| T39 | agent | professional:3 | neutral |
| T40 | agent | professional:3 | neutral |
| T41 | agent | warm:4 | happy |
| T42 | agent | warm:4 | happy |
| T43 | customer | tearful:3 | sad |
| T44 | agent | reassuring:4 | happy |
| T45 | customer | cooperative:3 | neutral |
| T46 | agent | professional:3 | neutral |
| T47 | customer | shocked:4 | surprised |
| T48 | agent | cautious:4 | neutral |
| T49 | customer | resolute_afraid:4 | frustrated |
| T50 | agent | firm:4 | neutral |
| T51 | customer | grateful_afraid:4 | happy |
| T52 | agent | reassuring:4 | happy |
| T53 | customer | resolute:3 | neutral |
| T54 | agent | warm:3 | happy |
| T55 | customer | relieved:4 | happy |
