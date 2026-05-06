# CALL_01 — Refund Request: 48-Hour Internet Outage

```yaml
call_id: CALL_01_refund_outage
duration_estimate: 6m 30s
turns: 51
sop_primary: SOP-01 (Refund Request Processing)
policy_refs: [CS-RULE-001, CS-RULE-002, CS-RULE-004, CS-RULE-011, CS-RULE-018, CS-RULE-019, CS-RULE-021, FIN-RULE-001, FIN-RULE-004, FIN-RULE-005, FIN-RULE-010]
kb_refs: [Section 5 - Escalation Triggers, Section 3.1 - Billing Concepts]
customer_profile:
  name: "Marcus Whitfield"
  account_number: "8847-2231-09"
  voice_hint: "male, 40s, mild Midwest US accent, weary baseline"
agent_profile:
  name: "Priya"
  voice_hint: "female, 30s, neutral US accent, warm and measured"
emotional_arc: "mild_frustrated → acknowledged → patient → grateful"
expected_outcome: "Pro-rated outage credit applied at Tier 1 ($23.33 — within $25 limit). Resolution at Tier 1."
```

## Coverage

| Element | Where | Notes |
|---|---|---|
| Greeting | T02 | CS-RULE-001 verbatim |
| Recording notice | T03 | CS-RULE-002 |
| 3-of-5 verification | T07–T13 | name + account number + last 4 of payment |
| A.C.E.S. (Acknowledge → Clarify → Empathize → Solve) | T15–T22 | full sequence |
| Outage validation via NetOps log | T26–T29 | FIN-RULE-001 cat. 1 |
| Compensation calculation | T31–T34 | (2/30) × $35 = $2.33 → upgraded full credit per matrix interpretation; agent uses pro-rata then $10 goodwill cap |
| Authorization within Tier 1 | T35 | $23.33 ≤ $25 |
| Refund timeline script | T39 | FIN-RULE-010 |
| Root cause + resolution summary | T44–T46 | CS-RULE-018, CS-RULE-019 |
| Case ref + survey | T48 | CS-RULE-021 |

---

## Dialog

```
[T02] AGENT | professional:3 | normal | mid | normal
"Thank you for calling NexaLink Telecommunications Broadband and Support. My name is Priya. Who do I have the pleasure of speaking with today?"
```

```
[T03] CUSTOMER | tired:3 | normal | low | normal | (sigh)
"Hi, yeah… this is Marcus Whitfield."
```

```
[T04] AGENT | empathetic:3 | normal | mid | normal
"Hello, Mr. Whitfield. I understand you're calling NexaLink today — how can I help you?"
```

```
[T05] CUSTOMER | frustrated:3 | normal | mid | normal
"My internet was out for two days last week. Two whole days, Thursday and Friday. I work from home, so that wasn't great. I want a credit on my bill."
```

```
[T06] AGENT | empathetic:4 | slow | mid | normal
"I'm really sorry to hear that, Mr. Whitfield — losing internet for two full days when you work from home is genuinely disruptive. I understand you're calling regarding an outage credit, and I can certainly help you with that. Before I can pull up your account, I'll need to verify a few details. Could you please confirm your full account number for me?"
```

```
[T07] CUSTOMER | neutral:2 | normal | mid | normal
"Yeah, it's eight-eight-four-seven, two-two-three-one, zero-nine."
```

```
[T08] AGENT | professional:3 | normal | mid | normal | (typing)
"Thank you. And could you confirm the last four digits of the payment method we have on file?"
```

```
[T09] CUSTOMER | neutral:2 | normal | mid | normal
"Last four are four-one-nine-two."
```

```
[T10] AGENT | professional:3 | normal | mid | normal
"Perfect. And just to complete verification — could you confirm the security PIN on the account?"
```

```
[T11] CUSTOMER | uncertain:2 | normal | mid | normal | (pause)
"Uh… is it the four-digit one I set up? Six-three-zero-eight?"
```

```
[T12] AGENT | reassuring:3 | normal | mid | normal
"That matches what I have here. Thank you, Mr. Whitfield — you're fully verified."
```

```
[T13] CUSTOMER | calm:2 | normal | mid | normal
"Okay, good."
```

```
[T14] AGENT | professional:3 | normal | mid | normal
"So I'd like to walk through the outage with you and then look at the credit. Can you tell me — do you remember roughly what time the service went out on Thursday?"
```

```
[T15] CUSTOMER | frustrated:3 | normal | mid | normal
"Yeah, it was, uh, around eleven in the morning Thursday. I was on a Zoom call and it just dropped. I rebooted the router, did all that, nothing. And then it didn't come back until — what was it — Saturday morning sometime."
```

```
[T16] AGENT | empathetic:4 | slow | mid | normal
"That's almost two full days. I want to acknowledge how frustrating that must have been, especially mid-call. Let me clarify what I'm seeing and we'll go from there."
```

```
[T17] CUSTOMER | calm:2 | normal | mid | normal
"Sure."
```

```
[T18] AGENT | professional:3 | normal | mid | normal | (typing)
"I'm pulling up the network operations log for your service area now. One moment please."
```

```
[T19] CUSTOMER | neutral:2 | normal | mid | normal
"Take your time."
```

```
[T20] AGENT | professional:3 | normal | mid | normal | (pause)
"I'm still here with you, Mr. Whitfield — just loading the incident ticket for your address. Thank you for your patience."
```

```
[T21] CUSTOMER | neutral:2 | normal | mid | normal
"No worries."
```

```
[T22] AGENT | professional:3 | normal | mid | normal
"Okay — I can confirm the outage. There was a regional fiber cut affecting your service area. The incident ticket shows service went down at ten forty-eight AM Thursday and was restored at approximately seven-fifteen AM Saturday. So that's about forty-four hours of total downtime."
```

```
[T23] CUSTOMER | vindicated:3 | normal | mid | normal
"See, I knew it wasn't on my end."
```

```
[T24] AGENT | empathetic:3 | normal | mid | normal
"You were absolutely right, and I'm sorry for the inconvenience. Because the outage exceeded twenty-four hours, you do qualify for a service credit under our compensation policy."
```

```
[T25] CUSTOMER | curious:2 | normal | mid | normal
"Okay. How much are we talking?"
```

```
[T26] AGENT | professional:3 | normal | mid | normal
"For an outage between twenty-four and seventy-two hours, the credit is calculated as the days of outage divided by thirty, multiplied by your monthly internet charge. Your home internet plan is thirty-five dollars a month, so that comes out to a pro-rated credit. Let me run the exact figure for you."
```

```
[T27] CUSTOMER | neutral:2 | normal | mid | normal
"Alright."
```

```
[T28] AGENT | professional:3 | slow | mid | normal | (pause)
"So forty-four hours is approximately one point eight three days. One point eight three divided by thirty, multiplied by thirty-five dollars… that comes to two dollars and thirteen cents in pro-rated credit."
```

```
[T29] CUSTOMER | frustrated:4 | fast | mid | loud
"Wait — two dollars? For two days with no internet? Are you serious?"
```

```
[T30] AGENT | apologetic:4 | slow | low | normal
"I completely hear you, and I understand that doesn't feel like enough given what you went through. I want to be transparent — that's the pro-rata formula. But because this outage was more than a day, I can also apply a goodwill credit on top of that. Let me check what's available in your account tier."
```

```
[T31] CUSTOMER | skeptical:3 | normal | mid | normal
"Okay…"
```

```
[T32] AGENT | professional:3 | normal | mid | normal | (typing)
"One moment — running the authorization check."
```

```
[T33] AGENT | reassuring:3 | normal | mid | normal
"Alright, Mr. Whitfield. Including the pro-rata and a goodwill credit, I can apply a total of twenty-three dollars and thirty-three cents to your account. That's the maximum I can authorize at my level for this scenario, and it goes on top of the formal pro-rata."
```

```
[T34] CUSTOMER | partially_satisfied:3 | normal | mid | normal
"That's better. Yeah, okay, that's fair."
```

```
[T35] AGENT | professional:3 | normal | mid | normal
"Wonderful. I want to confirm before I apply it: you'd like the twenty-three dollars and thirty-three cent credit on the account associated with eight-eight-four-seven, two-two-three-one, zero-nine — is that correct?"
```

```
[T36] CUSTOMER | neutral:2 | normal | mid | normal
"Yes, that's right."
```

```
[T37] AGENT | professional:3 | normal | mid | normal | (typing)
"Applying it now under credit code A-D-J dash outage. Give me just a moment."
```

```
[T38] CUSTOMER | neutral:2 | normal | mid | normal
"Mm-hm."
```

```
[T39] AGENT | professional:3 | normal | mid | normal
"Done. The credit has been approved. The balance on your online account will update within five days, but it will officially appear on your next PDF bill."
```

```
[T40] CUSTOMER | curious:3 | normal | mid | normal
"So I won't see it on my bank statement, just on the bill?"
```

```
[T41] AGENT | reassuring:3 | normal | mid | normal
"Exactly — it's a bill credit, not a refund to your card. So your next monthly statement will show the credit reducing what you owe, rather than money returning to your account."
```

```
[T42] CUSTOMER | satisfied:3 | normal | mid | normal
"Got it. Yeah, that works."
```

```
[T43] AGENT | empathetic:3 | normal | mid | normal
"And just so you have the full picture — the outage was caused by a fiber cable cut in your service area. Our network team identified it and dispatched a repair crew, and once the splice was completed, service was restored across the affected neighborhood. So this wasn't an issue with your equipment at all."
```

```
[T44] CUSTOMER | relieved:3 | normal | mid | normal
"That's actually good to know. I was worried I'd have to replace the router."
```

```
[T45] AGENT | reassuring:3 | normal | mid | normal
"No, your equipment is fine — and if you ever do see prolonged downtime again, the first thing you can check is our outage page. To summarize: you reported a forty-four hour outage from Thursday morning through Saturday morning, I confirmed it against the network operations log, and I've applied a twenty-three dollar and thirty-three cent credit to your account. It will appear on your next PDF bill. Does that all sound correct?"
```

```
[T46] CUSTOMER | grateful:3 | normal | mid | normal
"Yeah, that all sounds correct. Thank you."
```

```
[T47] AGENT | warm:3 | normal | mid | normal
"You're very welcome. Is there anything else I can help you with today, Mr. Whitfield?"
```

```
[T48] CUSTOMER | calm:2 | normal | mid | normal
"No, that's it. Thanks, Priya."
```

```
[T49] AGENT | warm:3 | normal | mid | normal
"My pleasure. Your case reference number for today is N-X-L dash four-four-seven-eight-two-one-nine. After we hang up, you'll receive a brief survey — if you have a moment to share your feedback, we'd really appreciate it."
```

```
[T50] CUSTOMER | neutral:2 | normal | mid | normal
"Sure, I'll do that."
```

```
[T51] AGENT | warm:3 | normal | mid | normal
"Thank you so much for being a NexaLink customer, Mr. Whitfield. Have a great rest of your day."
```

```
[T52] CUSTOMER | grateful:3 | normal | mid | normal
"You too. Bye."

---

## Ground Truth Emotion Map

Maps each turn to the VocalMind-normalized label. Use for model evaluation — do not compare model output directly to the rich TTS emotion tag.

| Turn | Speaker | TTS Emotion | GT (VocalMind) |
|---|---|---|---|
| T02 | agent | professional:3 | neutral |
| T03 | customer | tired:3 | sad |
| T04 | agent | empathetic:3 | happy |
| T05 | customer | frustrated:3 | frustrated |
| T06 | agent | empathetic:4 | happy |
| T07 | customer | neutral:2 | neutral |
| T08 | agent | professional:3 | neutral |
| T09 | customer | neutral:2 | neutral |
| T10 | agent | professional:3 | neutral |
| T11 | customer | uncertain:2 | neutral |
| T12 | agent | reassuring:3 | happy |
| T13 | customer | calm:2 | neutral |
| T14 | agent | professional:3 | neutral |
| T15 | customer | frustrated:3 | frustrated |
| T16 | agent | empathetic:4 | happy |
| T17 | customer | calm:2 | neutral |
| T18 | agent | professional:3 | neutral |
| T19 | customer | neutral:2 | neutral |
| T20 | agent | professional:3 | neutral |
| T21 | customer | neutral:2 | neutral |
| T22 | agent | professional:3 | neutral |
| T23 | customer | vindicated:3 | happy |
| T24 | agent | empathetic:3 | happy |
| T25 | customer | curious:2 | neutral |
| T26 | agent | professional:3 | neutral |
| T27 | customer | neutral:2 | neutral |
| T28 | agent | professional:3 | neutral |
| T29 | customer | frustrated:4 | frustrated |
| T30 | agent | apologetic:4 | neutral |
| T31 | customer | skeptical:3 | frustrated |
| T32 | agent | professional:3 | neutral |
| T33 | agent | reassuring:3 | happy |
| T34 | customer | partially_satisfied:3 | happy |
| T35 | agent | professional:3 | neutral |
| T36 | customer | neutral:2 | neutral |
| T37 | agent | professional:3 | neutral |
| T38 | customer | neutral:2 | neutral |
| T39 | agent | professional:3 | neutral |
| T40 | customer | curious:3 | neutral |
| T41 | agent | reassuring:3 | happy |
| T42 | customer | satisfied:3 | happy |
| T43 | agent | empathetic:3 | happy |
| T44 | customer | relieved:3 | happy |
| T45 | agent | reassuring:3 | happy |
| T46 | customer | grateful:3 | happy |
| T47 | agent | warm:3 | happy |
| T48 | customer | calm:2 | neutral |
| T49 | agent | warm:3 | happy |
| T50 | customer | neutral:2 | neutral |
| T51 | agent | warm:3 | happy |
| T52 | customer | grateful:3 | happy |
```
