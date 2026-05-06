# CALL_03 — Technical Support: Slow Home Internet (Path B Full Diagnostic)

```yaml
call_id: CALL_03_tech_support_slow_internet
duration_estimate: 5m 50s
turns: 54
sop_primary: SOP-03 (Technical Support Troubleshooting), Path B
policy_refs: [CS-RULE-001, CS-RULE-002, CS-RULE-004, CS-RULE-009, CS-RULE-011, CS-RULE-018, CS-RULE-019, CS-RULE-021, FIN-RULE-003]
kb_refs: [Section 2.1 - Technology Tiers, Section 2.2 - Router & WiFi, Section 5 - Escalation Triggers]
customer_profile:
  name: "Sofia Reyes"
  account_number: "7790-3322-15"
  voice_hint: "female, 30s, mild Spanish/Latin American accent (ESL but fluent), patient and slightly tired baseline"
agent_profile:
  name: "Marcus"
  voice_hint: "male, 30s, neutral US accent, friendly and methodical"
emotional_arc: "tired → cooperative → curious → relieved"
expected_outcome: "Resolution at Tier 1 — modem power-cycle restored speed. No escalation."
```

## Coverage

| Element | Where | Notes |
|---|---|---|
| Greeting + recording | T02–T03 | |
| 3-of-5 verification | T08–T13 | name + account + last 4 of SSN |
| Issue classification questions | T15–T19 | mobile vs home, all devices vs one, sudden vs gradual |
| Account status + outage check | T20–T22 | KB Section 5 |
| Path B steps in order | T24–T38 | speed test → device count → 5GHz → modem reboot |
| Hardwired test enforcement | T26 | FIN-RULE-003 |
| Resolution confirmation | T39–T41 | live test |
| Root cause explained | T43 | CS-RULE-018 |
| Resolution summary | T44 | CS-RULE-019 |
| Case ref + survey | T46 | CS-RULE-021 |
| Dead-air re-engagement | T34 | CS-RULE-009 |

---

## Dialog

```
[T02] AGENT | professional:3 | normal | mid | normal
"Thank you for calling NexaLink Telecommunications Broadband and Support. My name is Marcus. Who do I have the pleasure of speaking with today?"
```

```
[T03] CUSTOMER | tired:3 | slow | mid | normal | (sigh)
"Hi, my name is Sofia Reyes. I'm having problems with my internet — it's very, very slow."
```

```
[T04] AGENT | empathetic:3 | normal | mid | normal
"Hi, Sofia, I'm sorry to hear that. I understand you're calling about slow internet, and I can definitely help you with that. First, I just need to verify a few things on the account. Could you confirm your full account number for me?"
```

```
[T05] CUSTOMER | cooperative:2 | slow | mid | normal
"Yes. It is seven-seven-nine-zero, three-three-two-two, one-five."
```

```
[T06] AGENT | professional:3 | normal | mid | normal | (typing)
"Got it. Could you confirm the last four digits of the payment method we have on file?"
```

```
[T07] CUSTOMER | uncertain:2 | slow | mid | normal | (pause)
"Um, I think it's the credit card? Last four is two-six-five-five."
```

```
[T08] AGENT | reassuring:3 | normal | mid | normal
"Perfect, that matches. And one more — could you tell me the last four digits of your social security or national ID, or the security PIN, whichever is easier?"
```

```
[T09] CUSTOMER | cooperative:2 | normal | mid | normal
"The security PIN is one-zero-zero-eight."
```

```
[T10] AGENT | professional:3 | normal | mid | normal
"Wonderful. Sofia, you're fully verified. Thanks for being patient with that."
```

```
[T11] CUSTOMER | calm:2 | normal | mid | normal
"No problem."
```

```
[T12] AGENT | empathetic:3 | normal | mid | normal
"So I want to acknowledge — slow internet is honestly one of the most frustrating things, especially when you're trying to actually get something done. Let me ask a few quick questions so we can figure out exactly what's happening, okay?"
```

```
[T13] CUSTOMER | cooperative:3 | normal | mid | normal
"Yes, please."
```

```
[T14] AGENT | professional:3 | normal | mid | normal
"First — is this your home internet, or are you having mobile data issues?"
```

```
[T15] CUSTOMER | calm:2 | normal | mid | normal
"Home internet. The WiFi."
```

```
[T16] AGENT | professional:3 | normal | mid | normal
"Got it. Is the slow speed affecting all of your devices, or just one?"
```

```
[T17] CUSTOMER | thoughtful:2 | slow | mid | normal | (pause)
"All of them, I think. My laptop, my phone, the smart TV. Everything is slow."
```

```
[T18] AGENT | professional:3 | normal | mid | normal
"Okay, that's helpful. And was it sudden — like one day it just changed — or has it been getting slower over time?"
```

```
[T19] CUSTOMER | thoughtful:2 | slow | mid | normal
"It started maybe four days ago. Suddenly. Before that it was fine."
```

```
[T20] AGENT | professional:3 | normal | mid | normal
"Perfect. Thank you. Has anything changed in the home recently — new device, a router move, a power outage?"
```

```
[T21] CUSTOMER | thoughtful:3 | slow | mid | normal
"Hmm. There was a small power flicker last week. The lights blinked. Maybe Wednesday?"
```

```
[T22] AGENT | curious:3 | normal | mid | normal
"That's a useful clue. Let me first check that there's no outage in your area. One moment."
```

```
[T23] AGENT | professional:3 | normal | mid | normal | (typing)
"Okay — your account is active, no billing holds, and there are no reported outages in your service area. So this looks like a local issue we can troubleshoot together. Are you near your modem and router right now?"
```

```
[T24] CUSTOMER | calm:2 | normal | mid | normal
"Yes, I am sitting next to it."
```

```
[T25] AGENT | professional:3 | normal | mid | normal
"Wonderful. The first thing I'd like to do is run a speed test, but I need it to be accurate — so I need you to plug your laptop directly into the modem with an ethernet cable, if you have one. WiFi tests aren't precise enough for this."
```

```
[T26] CUSTOMER | uncertain:2 | slow | mid | normal | (pause)
"Ethernet cable… one moment, let me check… yes, I have one. Hold on, I will plug it in."
```

```
[T27] AGENT | reassuring:3 | normal | mid | normal
"Take your time, Sofia."
```

```
[T28] CUSTOMER | concentrating:2 | slow | mid | quiet
"Okay… plugging in now…"
```

```
[T29] CUSTOMER | calm:2 | normal | mid | normal
"Okay, it is plugged in."
```

```
[T30] AGENT | professional:3 | normal | mid | normal
"Great. Now please open a browser and go to nexalink dot speedtest. When the page loads, click the big start button and read me the download number when it finishes."
```

```
[T31] CUSTOMER | concentrating:2 | slow | mid | normal
"Okay… loading… clicking start now…"
```

```
[T32] AGENT | professional:3 | normal | mid | normal | (pause)
"I'm still here with you, Sofia — just waiting for the result. Thank you for your patience."
```

```
[T33] CUSTOMER | concerned:3 | normal | mid | normal
"It says… download is twenty-eight Mbps."
```

```
[T34] AGENT | professional:3 | normal | mid | normal
"And which plan are you on — do you remember? Looking here, I see you're on the two hundred Mbps fiber plan."
```

```
[T35] CUSTOMER | surprised:3 | normal | mid | normal
"Two hundred? But I'm getting twenty-eight? That's like ten percent."
```

```
[T36] AGENT | empathetic:3 | normal | mid | normal
"That's a real problem. You should be seeing close to two hundred on a wired test. Let me have you do a couple of things. How many devices are connected to your WiFi right now? Anything downloading or backing up?"
```

```
[T37] CUSTOMER | thoughtful:2 | slow | mid | normal
"Maybe… seven devices? But nothing is downloading. The TV is off."
```

```
[T38] AGENT | professional:3 | normal | mid | normal
"Okay. Seven is normal — that's not the cause. The fact that the wired speed is this low points to the modem itself. I'd like to power-cycle it. That means unplugging the power cable from the back of the modem, waiting a full thirty seconds, and plugging it back in. Can you do that?"
```

```
[T39] CUSTOMER | cooperative:2 | normal | mid | normal
"Yes. Unplugging now."
```

```
[T40] AGENT | professional:3 | normal | mid | normal
"Thirty seconds. I'll count with you if you'd like, or you can just plug it back in when you're ready. The lights on the front will start blinking — that's normal. Wait until they go solid before we test again. That usually takes one to two minutes."
```

```
[T41] CUSTOMER | calm:2 | slow | mid | normal | (pause)
"Okay… plugged in… the lights are blinking now."
```

```
[T42] AGENT | reassuring:3 | normal | mid | normal
"Perfect. Let's give it a moment. While we wait — that power flicker you mentioned last Wednesday is most likely what caused this. The modem can hang in a degraded state after a brief power loss. The full power-cycle is what fixes it."
```

```
[T43] CUSTOMER | curious:3 | normal | mid | normal
"Oh, interesting. So a small flicker can do this?"
```

```
[T44] AGENT | warm:3 | normal | mid | normal
"Surprisingly, yes — the modem doesn't always recover automatically. Are the lights solid yet?"
```

```
[T45] CUSTOMER | cooperative:2 | normal | mid | normal
"Yes, they are solid now. Green and white."
```

```
[T46] AGENT | professional:3 | normal | mid | normal
"Wonderful. Now let's run the speed test one more time on the wired connection."
```

```
[T47] CUSTOMER | curious:3 | normal | mid | normal | (pause)
"Okay… running it… "
```

```
[T48] CUSTOMER | relieved:4 | normal | high | normal
"Oh! Two hundred and twelve Mbps! It's working!"
```

```
[T49] AGENT | warm:4 | normal | mid | normal
"There we go! That's right where you should be. So just to summarize what happened — the brief power flicker last week left the modem in a degraded state, the full thirty-second power cycle reset its connection to the network, and you're now getting full speed. Does that all make sense?"
```

```
[T50] CUSTOMER | grateful:3 | normal | mid | normal
"Yes, it makes sense. Thank you so much, Marcus. I was thinking I would have to buy a new router."
```

```
[T51] AGENT | warm:3 | normal | mid | normal
"No, your equipment is fine. And just so you know for the future — if you ever see speeds drop suddenly again, the very first thing to try is that thirty-second power cycle. If it ever doesn't fix it, give us a call right away. Is there anything else I can help you with today, Sofia?"
```

```
[T52] CUSTOMER | satisfied:3 | normal | mid | normal
"No, that is all. You were very helpful."
```

```
[T53] AGENT | warm:3 | normal | mid | normal
"Thank you for saying that. Your case reference number for today is N-X-L dash four-four-eight-zero-three-six-six. After we hang up, you'll get a quick survey — if you have a moment, your feedback really helps us."
```

```
[T54] CUSTOMER | warm:3 | normal | mid | normal
"Of course. Goodbye, Marcus."
```

```
[T55] AGENT | warm:3 | normal | mid | normal
"Have a wonderful day, Sofia."

---

## Ground Truth Emotion Map

| Turn | Speaker | TTS Emotion | GT (VocalMind) |
|---|---|---|---|
| T02 | agent | professional:3 | neutral |
| T03 | customer | tired:3 | sad |
| T04 | agent | empathetic:3 | happy |
| T05 | customer | cooperative:2 | neutral |
| T06 | agent | professional:3 | neutral |
| T07 | customer | uncertain:2 | neutral |
| T08 | agent | reassuring:3 | happy |
| T09 | customer | cooperative:2 | neutral |
| T10 | agent | professional:3 | neutral |
| T11 | customer | calm:2 | neutral |
| T12 | agent | empathetic:3 | happy |
| T13 | customer | cooperative:3 | neutral |
| T14 | agent | professional:3 | neutral |
| T15 | customer | calm:2 | neutral |
| T16 | agent | professional:3 | neutral |
| T17 | customer | thoughtful:2 | neutral |
| T18 | agent | professional:3 | neutral |
| T19 | customer | thoughtful:2 | neutral |
| T20 | agent | professional:3 | neutral |
| T21 | customer | thoughtful:3 | neutral |
| T22 | agent | curious:3 | neutral |
| T23 | agent | professional:3 | neutral |
| T24 | customer | calm:2 | neutral |
| T25 | agent | professional:3 | neutral |
| T26 | customer | uncertain:2 | neutral |
| T27 | agent | reassuring:3 | happy |
| T28 | customer | concentrating:2 | neutral |
| T29 | customer | calm:2 | neutral |
| T30 | agent | professional:3 | neutral |
| T31 | customer | concentrating:2 | neutral |
| T32 | agent | professional:3 | neutral |
| T33 | customer | concerned:3 | frustrated |
| T34 | agent | professional:3 | neutral |
| T35 | customer | surprised:3 | surprised |
| T36 | agent | empathetic:3 | happy |
| T37 | customer | thoughtful:2 | neutral |
| T38 | agent | professional:3 | neutral |
| T39 | customer | cooperative:2 | neutral |
| T40 | agent | professional:3 | neutral |
| T41 | customer | calm:2 | neutral |
| T42 | agent | reassuring:3 | happy |
| T43 | customer | curious:3 | neutral |
| T44 | agent | warm:3 | happy |
| T45 | customer | cooperative:2 | neutral |
| T46 | agent | professional:3 | neutral |
| T47 | customer | curious:3 | neutral |
| T48 | customer | relieved:4 | happy |
| T49 | agent | warm:4 | happy |
| T50 | customer | grateful:3 | happy |
| T51 | agent | warm:3 | happy |
| T52 | customer | satisfied:3 | happy |
| T53 | agent | warm:3 | happy |
| T54 | customer | warm:3 | happy |
| T55 | agent | warm:3 | happy |
```
