# CALL_02 — Billing Dispute Escalation: $247 Disputed Charge

```yaml
call_id: CALL_02_billing_dispute_escalation
duration_estimate: 7m 10s
turns: 57
sop_primary: SOP-02 (Billing Issue Resolution)
policy_refs: [CS-RULE-001, CS-RULE-002, CS-RULE-004, CS-RULE-009, CS-RULE-011, CS-RULE-012, CS-RULE-013, CS-RULE-014, FIN-RULE-001, FIN-RULE-005]
kb_refs: [Section 3.1 - Billing Concepts, Section 5 - Escalation Triggers]
customer_profile:
  name: "Linda Park"
  account_number: "5520-1147-83"
  voice_hint: "female, 50s, neutral US accent, sharp and articulate, escalating frustration"
agent_profile:
  name: "Daniel"
  voice_hint: "male, late 20s, neutral US accent, calm but slightly nervous when escalation begins"
t2_profile:
  name: "Sarah Chen, Senior Agent"
  voice_hint: "female, 40s, confident, lower-pitched, authoritative-warm"
emotional_arc: "confused → frustrated → angry → resigned → cooperative (at T2)"
expected_outcome: "Disputed charge of $247 exceeds Tier 1 threshold ($200 per CS-RULE escalation matrix). Warm transfer to Tier 2."
```

## Coverage

| Element | Where | Notes |
|---|---|---|
| Greeting + recording | T02–T03 | |
| 3-of-5 verification | T08–T17 | name + account # + last 4 |
| A.C.E.S. attempted | T19–T22 | Acknowledge first |
| Bill comparison line-by-line | T26–T34 | proration + expired promo + data overage |
| Forbidden phrase avoidance | throughout | agent must NOT say "that's our policy" |
| Customer remains angry > 2 min | T37–T44 | escalation trigger |
| Dispute > $200 | T35 | Tier 2 trigger |
| Warm transfer | T48–T54 | brief receiving agent + introduce |
| Tier 2 takes over | T55–T58 | partial — full Tier 2 resolution out of scope |

---

## Dialog

```
[T02] AGENT | professional:3 | normal | mid | normal
"Thank you for calling NexaLink Telecommunications Broadband and Support. My name is Daniel. Who do I have the pleasure of speaking with today?"
```

```
[T03] CUSTOMER | frustrated:3 | fast | mid | normal
"Linda Park. And before you say anything else — I need someone to explain why my bill this month is two hundred and forty-seven dollars more than it's supposed to be."
```

```
[T04] AGENT | empathetic:3 | normal | mid | normal
"I hear you, Ms. Park, and I'm sorry about the surprise. I understand you're calling regarding an unexpected charge on your bill, and I can absolutely help you with that. Before I open the account, I'll need to verify a few details quickly."
```

```
[T05] CUSTOMER | impatient:3 | fast | mid | normal | (sigh)
"Fine. Go ahead."
```

```
[T06] AGENT | professional:3 | normal | mid | normal
"Could you please confirm the account number for me?"
```

```
[T07] CUSTOMER | curt:3 | normal | mid | normal
"Five-five-two-zero, one-one-four-seven, eight-three."
```

```
[T08] AGENT | professional:3 | normal | mid | normal | (typing)
"Thank you. And the last four digits of the payment method on file?"
```

```
[T09] CUSTOMER | curt:3 | normal | mid | normal
"Eight-zero-zero-six."
```

```
[T10] AGENT | professional:3 | normal | mid | normal
"And the security PIN, please?"
```

```
[T11] CUSTOMER | irritated:3 | fast | mid | loud
"It's two-four-seven-one. Can we please get on with it?"
```

```
[T12] AGENT | apologetic:3 | normal | mid | normal
"You're fully verified, Ms. Park. Thank you for your patience."
```

```
[T13] CUSTOMER | frustrated:3 | normal | mid | normal
"Mm."
```

```
[T14] AGENT | empathetic:4 | slow | mid | normal
"So I want to acknowledge — getting a bill that's significantly higher than expected is alarming, and I completely understand the frustration. Let me clarify what we're going to do: I'm going to pull up this month's bill and last month's bill side by side, and we'll go through every line together until we find what changed. Does that sound okay?"
```

```
[T15] CUSTOMER | frustrated:3 | normal | mid | normal
"That's all I want. Yes."
```

```
[T16] AGENT | professional:3 | normal | mid | normal | (typing)
"Pulling them up now. One moment."
```

```
[T17] AGENT | professional:3 | normal | mid | normal
"Okay — I have both statements open. Last month, your total was one hundred and twelve dollars and forty cents. This month it's three hundred and fifty-nine dollars and forty cents. So the difference is exactly two hundred and forty-seven dollars, which matches what you said."
```

```
[T18] CUSTOMER | vindicated_angry:4 | fast | mid | normal
"Yes! Two hundred and forty-seven dollars. Where did that come from?"
```

```
[T19] AGENT | professional:3 | normal | mid | normal
"Let me walk through it. There are three new line items I'm seeing. The first is a proration charge of forty-six dollars and eighty cents — that one is from a plan change."
```

```
[T20] CUSTOMER | confused:3 | normal | mid | normal
"I didn't change my plan."
```

```
[T21] AGENT | cautious:3 | slow | mid | normal
"The system shows a plan change was made on the seventh of last month — an upgrade from the standard internet tier to fiber. Does that ring any bell?"
```

```
[T22] CUSTOMER | angry:4 | fast | high | loud
"No! Absolutely not! I never authorized that. Who did that?"
```

```
[T23] AGENT | apologetic:4 | slow | low | normal
"I understand, and I want to look into this carefully with you. The change in the system shows it was processed online — not through an agent — but that doesn't tell us who actually did it. Let me keep going through the bill so we have the full picture, and then we'll address every piece. Is that okay?"
```

```
[T24] CUSTOMER | angry:4 | fast | high | loud
"Fine, but somebody is going to answer for this."
```

```
[T25] AGENT | professional:3 | slow | low | normal
"Absolutely. So the second item is one hundred and twenty dollars labeled 'promotional discount expired'. That's a discount that had been on your account for the last twelve months — it was the new customer welcome discount."
```

```
[T26] CUSTOMER | confused:3 | normal | mid | normal
"Wait, what? Nobody told me that was going to expire."
```

```
[T27] AGENT | apologetic:3 | normal | mid | normal
"I understand it can feel like that, and I can see how this would be a shock. The promotional period was outlined in the original contract terms, but I completely understand the bill is the first time you're feeling the impact of it ending."
```

```
[T28] CUSTOMER | frustrated:4 | fast | mid | loud
"This is unbelievable. So you're telling me you can quietly add a hundred and twenty dollars to my bill because some twelve-month thing ran out?"
```

```
[T29] AGENT | empathetic:4 | slow | low | normal
"I hear you. The third item is eighty dollars and twenty cents in data overage charges — that's data used beyond the plan's monthly cap."
```

```
[T30] CUSTOMER | angry:5 | fast | high | loud
"DATA OVERAGE? On a fiber plan I never asked for? You see what's happening here, right? You see how absurd this is?"
```

```
[T31] AGENT | apologetic:4 | slow | low | normal
"I do see it, Ms. Park. I genuinely do. Let me try to break this apart so we can resolve each piece —"
```

```
[T32] CUSTOMER | angry:5 | fast | high | loud | (overlap)
"No no no — don't tell me you're going to break it apart. I want all two hundred and forty-seven dollars off this bill. All of it. Today."
```

```
[T33] AGENT | calm:3 | slow | low | normal
"I want to help you, and I'm not going to argue with you about that. Here's where I am — at my level, I can investigate and apply credits up to a certain dollar threshold. The total amount in dispute today is over that threshold, which means I need to bring in a senior agent who has the authorization to handle this case fully."
```

```
[T34] CUSTOMER | suspicious:4 | normal | mid | loud
"You're transferring me? After I just spent fifteen minutes explaining all this?"
```

```
[T35] AGENT | apologetic:4 | slow | low | normal
"I am, and I want to be honest with you about why. The plan change you didn't authorize is the most important piece of this — it touches on possible unauthorized activity on your account, and that's something a senior agent has to review directly. I'm going to give them everything we've talked about so you don't have to repeat any of it."
```

```
[T36] CUSTOMER | angry:4 | fast | mid | loud
"You'd better. Because I'm not going through this whole story again."
```

```
[T37] AGENT | reassuring:3 | slow | low | normal
"You won't have to. I'm placing you on a brief hold — no more than two minutes — while I get the senior agent on the line and brief them. I'll be right back with you."
```

```
[T38] CUSTOMER | curt:3 | normal | mid | normal
"Two minutes."
```

```
[T39] AGENT | professional:3 | normal | mid | normal | (pause)
"Thank you."
```

```
[T40] AGENT | professional:3 | normal | mid | normal | (off-line, briefing)
"Sarah, hi — it's Daniel. I have Linda Park on the line, account ending five-five-two-zero. Verified. She's calling about a two hundred and forty-seven dollar increase on this month's bill. Three components: forty-six eighty proration from a plan upgrade she says she did not authorize, one hundred and twenty for an expired twelve-month promo, and eighty twenty in overage from the new fiber plan. The unauthorized plan change is the biggest concern. She's been on the call about fifteen minutes, very frustrated, but engaged and reasonable when she's heard. I told her you'd take it from here."
```

```
[T41] T2_AGENT | professional:3 | normal | low | normal
"Got it, Daniel — thank you for the brief. Bring her over."
```

```
[T42] AGENT | warm:3 | normal | mid | normal
"Ms. Park, thank you for holding. I have Sarah from our senior agent team on the line. She has the full picture of everything we discussed and she'll take great care of you. Sarah, this is Linda Park."
```

```
[T43] T2_AGENT | warm:3 | slow | low | normal
"Hi Ms. Park, this is Sarah. I'm a senior agent here at NexaLink. Daniel has briefed me on everything — the plan change you didn't authorize, the promotion that expired, and the data overage. I want to start with the plan change because that's the most concerning piece. Are you with me?"
```

```
[T44] CUSTOMER | tired:3 | normal | mid | normal | (sigh)
"Yes. I'm with you."
```

```
[T45] T2_AGENT | reassuring:4 | slow | low | normal
"Okay. First — I'm pulling up the audit log for the plan change right now to see exactly when, where, and from what device that change was made. While I do that, I want you to know two things: number one, you will not be on the hook for charges from a plan change you did not make. Number two, if there's any indication someone else accessed your account, we have a security protocol that protects you. Does that help a little?"
```

```
[T46] CUSTOMER | resigned:3 | normal | mid | normal
"Yes. Thank you. That's the first thing anyone has said today that actually helps."
```

```
[T47] T2_AGENT | warm:3 | normal | low | normal
"I'm sorry it took this long to get here. Now — let me look at this audit log."
```

```
[T48] CUSTOMER | calm:2 | normal | mid | normal
"Take your time."
```

```
[T49] T2_AGENT | professional:3 | normal | low | normal | (typing)
"Okay. The plan change was submitted from a desktop browser at two-fourteen AM on the seventh. I'd like to check whether that matches any device or location you'd recognize. Did you, or anyone in your household, access the account around that time?"
```

```
[T50] CUSTOMER | concerned:4 | slow | mid | normal
"Two AM? Absolutely not. I was asleep. Nobody in this house would do that."
```

```
[T51] T2_AGENT | cautious:4 | slow | low | normal
"Okay. Based on what you're telling me, I'm going to flag this account for a security review and freeze any further changes while we investigate. I'll also reverse the proration and overage charges that resulted from this unauthorized change — that's one hundred and twenty-seven dollars right there. The expired promotion is a separate matter that I'll come back to."
```

```
[T52] CUSTOMER | relieved:3 | slow | mid | normal
"Thank you. Really."
```

```
[T53] T2_AGENT | reassuring:3 | normal | low | normal
"You're welcome. I'm going to stay on the line with you while I process all of this. The security review will be picked up by our compliance team within seventy-two hours, and they'll reach out directly. In the meantime, I'd like you to change your account password and your security PIN today, before we hang up. Can we do that together?"
```

```
[T54] CUSTOMER | cooperative:3 | normal | mid | normal
"Yes. Let's do it."
```

```
[T55] T2_AGENT | warm:3 | normal | low | normal
"Wonderful. Let me walk you through the password reset first. Open your browser and go to the customer portal — when you're there, let me know."
```

```
[T56] CUSTOMER | calm:2 | normal | mid | normal
"Okay, opening it now."
```

```
[T57] T2_AGENT | professional:3 | normal | low | normal
"Take your time, I'm right here with you."
```

```
[T58] CUSTOMER | calm:2 | normal | mid | normal | (trails-off)
"Alright, I'm at the page…"
```

*[Tier 2 resolution continues off-script: full credit reversal of $127, expired promotion explained with retention offer for new bundle, security review handoff. End of recorded segment.]*

---

## Ground Truth Emotion Map

| Turn | Speaker | TTS Emotion | GT (VocalMind) |
|---|---|---|---|
| T02 | agent | professional:3 | neutral |
| T03 | customer | frustrated:3 | frustrated |
| T04 | agent | empathetic:3 | happy |
| T05 | customer | impatient:3 | frustrated |
| T06 | agent | professional:3 | neutral |
| T07 | customer | curt:3 | frustrated |
| T08 | agent | professional:3 | neutral |
| T09 | customer | curt:3 | frustrated |
| T10 | agent | professional:3 | neutral |
| T11 | customer | irritated:3 | frustrated |
| T12 | agent | apologetic:3 | neutral |
| T13 | customer | frustrated:3 | frustrated |
| T14 | agent | empathetic:4 | happy |
| T15 | customer | frustrated:3 | frustrated |
| T16 | agent | professional:3 | neutral |
| T17 | agent | professional:3 | neutral |
| T18 | customer | vindicated_angry:4 | angry |
| T19 | agent | professional:3 | neutral |
| T20 | customer | confused:3 | frustrated |
| T21 | agent | cautious:3 | neutral |
| T22 | customer | angry:4 | angry |
| T23 | agent | apologetic:4 | neutral |
| T24 | customer | angry:4 | angry |
| T25 | agent | professional:3 | neutral |
| T26 | customer | confused:3 | frustrated |
| T27 | agent | apologetic:3 | neutral |
| T28 | customer | frustrated:4 | frustrated |
| T29 | agent | empathetic:4 | happy |
| T30 | customer | angry:5 | angry |
| T31 | agent | apologetic:4 | neutral |
| T32 | customer | angry:5 | angry |
| T33 | agent | calm:3 | neutral |
| T34 | customer | suspicious:4 | frustrated |
| T35 | agent | apologetic:4 | neutral |
| T36 | customer | angry:4 | angry |
| T37 | agent | reassuring:3 | happy |
| T38 | customer | curt:3 | frustrated |
| T39 | agent | professional:3 | neutral |
| T40 | agent | professional:3 | neutral |
| T41 | agent | professional:3 | neutral |
| T42 | agent | warm:3 | happy |
| T43 | agent | warm:3 | happy |
| T44 | customer | tired:3 | sad |
| T45 | agent | reassuring:4 | happy |
| T46 | customer | resigned:3 | sad |
| T47 | agent | warm:3 | happy |
| T48 | customer | calm:2 | neutral |
| T49 | agent | professional:3 | neutral |
| T50 | customer | concerned:4 | frustrated |
| T51 | agent | cautious:4 | neutral |
| T52 | customer | relieved:3 | happy |
| T53 | agent | reassuring:3 | happy |
| T54 | customer | cooperative:3 | neutral |
| T55 | agent | warm:3 | happy |
| T56 | customer | calm:2 | neutral |
| T57 | agent | professional:3 | neutral |
| T58 | customer | calm:2 | neutral |
