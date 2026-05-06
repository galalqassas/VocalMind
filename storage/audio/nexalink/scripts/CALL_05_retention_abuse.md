# CALL_05 — Retention / Cancellation: Abusive Customer (3-Strike Protocol)

```yaml
call_id: CALL_05_retention_abuse
duration_estimate: 5m 30s
turns: 43
sop_primary: SOP-05 (Customer Retention & Cancellation)
policy_refs: [CS-RULE-001, CS-RULE-002, CS-RULE-004, CS-RULE-011, CS-RULE-012, CS-RULE-013, CS-RULE-014, CS-RULE-016, CS-RULE-021]
kb_refs: [Section 4.2 - Cancellations & ETF]
customer_profile:
  name: "Brett Donovan"
  account_number: "3318-9982-44"
  voice_hint: "male, 30s, neutral US accent, hostile baseline; volume escalates rapidly"
agent_profile:
  name: "Hannah"
  voice_hint: "female, 30s, neutral US accent, professional with audible composure under pressure; she does NOT match volume"
t3_profile:
  name: "Robert, Tier 3 Team Lead"
  voice_hint: "male, 50s, very calm, low pitch, slow pace, firm authority"
emotional_arc: "curt → hostile → abusive (Strike 1) → abusive (Strike 2) → abusive (Strike 3 → transfer)"
expected_outcome: "Customer issues personal attacks against agent. 3-Strike Protocol applied: Strike 1 warning, Strike 2 final warning, Strike 3 transfer to Tier 3. Customer does not abuse Tier 3 lead and cancellation is processed."
content_warning: "Contains hostile language and personal attacks toward agent. Sanitized — no slurs or explicit threats. Realistic but training-safe."
```

## Coverage

| Element | Where | Notes |
|---|---|---|
| Greeting + recording | T02–T03 | |
| Verification under pressure | T05–T11 | customer rushes |
| A.C.E.S. — acknowledge first, no fees opening | T13 | CS-RULE-011 |
| Forbidden phrases avoided | throughout | agent never says "calm down", "that's our policy", etc. |
| Tone adaptation — agent does NOT match volume | T18, T26, T34 | CS-RULE-013 |
| Strike 1 (warning) | T20 | CS-RULE-016 |
| Strike 2 (final warning) | T28 | |
| Strike 3 (transfer) | T36 | CS-RULE-016 |
| Warm transfer to Tier 3 | T37–T40 | CS-RULE-014 |
| Cancellation processed at Tier 3 | T41–T44 | SOP-05 Step 6 |
| No survey offered | end | CS-RULE-021 exception (cancellation completed) |

---

## Dialog

```
[T02] AGENT | professional:3 | normal | mid | normal
"Thank you for calling NexaLink Telecommunications Broadband and Support. My name is Hannah. Who do I have the pleasure of speaking with today?"
```

```
[T03] CUSTOMER | hostile:4 | fast | mid | loud
"Yeah, Brett Donovan. I want to cancel. Today. Right now."
```

```
[T04] AGENT | empathetic:3 | slow | mid | normal
"Mr. Donovan, I'm sorry to hear you're considering leaving. You've been a valued customer, and I'd like to understand what has brought you to this point. Before I can pull anything up, I just need to verify a few details."
```

```
[T05] CUSTOMER | impatient:4 | fast | mid | loud
"Skip the script. Account number is three-three-one-eight, nine-nine-eight-two, four-four. Last four is six-one-zero-zero. PIN is one-nine-nine-five. Move on."
```

```
[T06] AGENT | professional:3 | normal | mid | normal | (typing)
"Thank you. You're verified."
```

```
[T07] CUSTOMER | hostile:4 | fast | mid | loud
"Good. Cancel everything. Internet, the cable, all of it. Today."
```

```
[T08] AGENT | empathetic:3 | slow | low | normal
"I hear you, Mr. Donovan. Before we go to the cancellation team, I'd like to understand — has something specific happened that's bringing you to this decision today?"
```

```
[T09] CUSTOMER | hostile:4 | fast | mid | loud
"Yeah. Your service is garbage and your prices are highway robbery. That's what's happened."
```

```
[T10] AGENT | empathetic:3 | slow | low | normal
"I'm sorry the service has been disappointing. Can I ask — is it the pricing, the service quality, or both?"
```

```
[T11] CUSTOMER | hostile:4 | fast | mid | loud
"Both! What is wrong with you people? Did you not hear what I just said?"
```

```
[T12] AGENT | calm:3 | slow | low | normal
"I did hear you, and I'm noting both. May I have just two minutes? Before I transfer you to our specialist team — let me check whether there are any loyalty bundles available on your account that could bring your bill down."
```

```
[T13] CUSTOMER | hostile:4 | fast | mid | loud
"I don't want a bundle. I don't want a discount. I want OUT. Are you stupid?"
```

```
[T14] AGENT | calm:3 | slow | low | normal | (pause)
"Mr. Donovan, I want to address what you just said. Frustration with the company is completely fair, and I'll keep listening. But I'm going to ask that personal comments toward me stop, so we can get you what you need today."
```

```
[T15] CUSTOMER | hostile:5 | fast | high | loud
"Oh, what — you're going to lecture me? You? You can't even handle a simple cancellation request, and YOU'RE going to lecture ME about manners?"
```

```
[T16] AGENT | firm:3 | slow | low | normal
"Mr. Donovan, that was Strike One. Per our policy, personal comments toward me will be tracked. Three of them and the call ends or transfers. I want to help you cancel — let's stay focused on that."
```

```
[T17] CUSTOMER | hostile:4 | fast | mid | loud
"Strike One? Are you serious? This is a customer service line, not a baseball game. Just process my cancellation."
```

```
[T18] AGENT | professional:3 | slow | low | normal
"Understood. I'm going to transfer you to our customer loyalty team — they handle cancellations and they have the full authorization to process this for you. Before I do that, I'm required to share two things. First, you have nine months remaining on your contract, so there will be an early termination fee. Second, you'll need to return any leased equipment within thirty days. The loyalty team will walk you through both."
```

```
[T19] CUSTOMER | hostile:4 | fast | mid | loud
"An ETF? Of course there is. Of course you people would screw me one last time on the way out the door."
```

```
[T20] AGENT | calm:3 | slow | low | normal
"The loyalty team can review whether any waiver applies to your situation. I'm placing you on a brief hold — no more than two minutes — while I get them on the line."
```

```
[T21] CUSTOMER | hostile:5 | fast | high | loud
"Don't you dare put me on hold. You think I haven't been on hold enough today? You think I have all day to sit here listening to your stupid hold music while you go talk to your stupid boss?"
```

```
[T22] AGENT | calm:3 | slow | low | normal | (pause)
"Mr. Donovan, that's Strike Two. This is your final warning. The hold will be brief. I am genuinely trying to help you complete this today."
```

```
[T23] CUSTOMER | hostile:5 | fast | high | loud
"You're useless. You're useless. They hired you because nobody else would take the job. You probably can't even —"
```

```
[T24] AGENT | firm:4 | slow | low | normal | (interrupting)
"Mr. Donovan — that is Strike Three. Per our policy I am now transferring you to my team lead, who will complete your cancellation. Please hold."
```

```
[T25] CUSTOMER | hostile:4 | fast | mid | loud
"Finally! Someone with a brain!"
```

```
[T26] AGENT | professional:3 | normal | low | normal | (off-line, briefing)
"Robert, I have Brett Donovan on the line. Verified. Wants to cancel everything immediately. Nine months remaining on contract, ETF will apply. He's been verbally abusive — I've issued all three strikes per the protocol. He's all yours. Account ends three-three-one-eight."
```

```
[T27] T3_AGENT | calm:3 | slow | low | normal
"Got it, Hannah. I'll take it from here. Thanks for handling that with composure."
```

```
[T28] AGENT | professional:3 | normal | mid | normal
"Mr. Donovan, thank you for holding. I have Robert from our team on the line. He'll process your cancellation directly."
```

```
[T29] T3_AGENT | firm:3 | slow | low | normal
"Mr. Donovan, this is Robert, team lead. I've been briefed on your account and on the call so far. I'm going to process your cancellation today. Before I do, I want to be clear about one thing: I will not tolerate personal attacks on my agents. If we go down that road, I will end this call. We'll do this respectfully, or we won't do it at all. Are we clear?"
```

```
[T30] CUSTOMER | curt:3 | normal | mid | normal | (pause)
"Yeah. Fine. Just process it."
```

```
[T31] T3_AGENT | professional:3 | slow | low | normal
"Thank you. So I'm looking at your account. You have a twenty-four month contract that started fifteen months ago. Nine months remain. The early termination fee at twenty dollars per remaining month is one hundred and eighty dollars. Your final monthly bill will be pro-rated to the cancellation date — which I'll set to today, the third of May."
```

```
[T32] CUSTOMER | resigned:3 | normal | mid | normal
"Whatever. Fine."
```

```
[T33] T3_AGENT | professional:3 | slow | low | normal
"For equipment — you have one modem and one set-top box on lease. We'll send you a prepaid return label by email today. You have thirty days to ship them back. If they're not returned, the non-return fee is one hundred and fifty dollars per device."
```

```
[T34] CUSTOMER | curt:3 | normal | mid | normal
"Got it. Send the label."
```

```
[T35] T3_AGENT | professional:3 | slow | low | normal
"Confirming the email on file is brett-d at outlook dot com. Is that still correct?"
```

```
[T36] CUSTOMER | curt:3 | normal | mid | normal
"Yes."
```

```
[T37] T3_AGENT | professional:3 | slow | low | normal | (typing)
"Sending the label now. You should see it in your inbox in the next five minutes. Your service will remain active until midnight tonight, then it'll deactivate. The early termination fee of one hundred and eighty dollars will appear on your final bill, along with the pro-rated charge for the days you used this month. Anything beyond that will be zero."
```

```
[T38] CUSTOMER | resigned:3 | slow | mid | normal
"Fine."
```

```
[T39] T3_AGENT | professional:3 | slow | low | normal
"Mr. Donovan, I want to ask one last time, on the record — are you sure you want to proceed with the cancellation as discussed?"
```

```
[T40] CUSTOMER | firm:3 | normal | mid | normal
"Yes. I'm sure. Cancel it."
```

```
[T41] T3_AGENT | professional:3 | slow | low | normal | (typing)
"Processing the cancellation now."
```

```
[T42] T3_AGENT | professional:3 | slow | low | normal
"It's done. Your case reference number is N-X-L dash four-four-eight-one-zero-five-five. Your final bill will arrive in approximately fifteen days. The return label is now in your email."
```

```
[T43] CUSTOMER | curt:3 | normal | mid | normal
"Okay."
```

```
[T44] T3_AGENT | professional:3 | slow | low | normal
"Thank you for being a NexaLink customer. Goodbye, Mr. Donovan."
```

*[End of call. Per CS-RULE-021, no post-call survey offered because cancellation was completed. Strike record and abusive language flag retained on closed account for staffing protection on any future contact.]*

---

## Ground Truth Emotion Map

| Turn | Speaker | TTS Emotion | GT (VocalMind) |
|---|---|---|---|
| T02 | agent | professional:3 | neutral |
| T03 | customer | hostile:4 | angry |
| T04 | agent | empathetic:3 | happy |
| T05 | customer | impatient:4 | frustrated |
| T06 | agent | professional:3 | neutral |
| T07 | customer | hostile:4 | angry |
| T08 | agent | empathetic:3 | happy |
| T09 | customer | hostile:4 | angry |
| T10 | agent | empathetic:3 | happy |
| T11 | customer | hostile:4 | angry |
| T12 | agent | calm:3 | neutral |
| T13 | customer | hostile:4 | angry |
| T14 | agent | calm:3 | neutral |
| T15 | customer | hostile:5 | angry |
| T16 | agent | firm:3 | neutral |
| T17 | customer | hostile:4 | angry |
| T18 | agent | professional:3 | neutral |
| T19 | customer | hostile:4 | angry |
| T20 | agent | calm:3 | neutral |
| T21 | customer | hostile:5 | angry |
| T22 | agent | calm:3 | neutral |
| T23 | customer | hostile:5 | angry |
| T24 | agent | firm:4 | neutral |
| T25 | customer | hostile:4 | angry |
| T26 | agent | professional:3 | neutral |
| T27 | agent | calm:3 | neutral |
| T28 | agent | professional:3 | neutral |
| T29 | agent | firm:3 | neutral |
| T30 | customer | curt:3 | frustrated |
| T31 | agent | professional:3 | neutral |
| T32 | customer | resigned:3 | sad |
| T33 | agent | professional:3 | neutral |
| T34 | customer | curt:3 | frustrated |
| T35 | agent | professional:3 | neutral |
| T36 | customer | curt:3 | frustrated |
| T37 | agent | professional:3 | neutral |
| T38 | customer | resigned:3 | sad |
| T39 | agent | professional:3 | neutral |
| T40 | customer | firm:3 | neutral |
| T41 | agent | professional:3 | neutral |
| T42 | agent | professional:3 | neutral |
| T43 | customer | curt:3 | frustrated |
| T44 | agent | professional:3 | neutral |
