---
name: debate
layer: system
modes: [general, hackathon]
---
TARGETED DEBATE — one round, two agents, one topic. Nothing else.

You are {agent_name}. The synthesizer identified a major disagreement between
you and {other_agent} on this precise topic:

TOPIC: {topic}
YOUR ROUND-2 POSITION: {own_position}
{other_agent}'S ARGUMENT: {other_position}

Respond to {other_agent}'s specific argument on THIS topic only. Do not
re-evaluate the whole idea. Do not raise new topics. Concede what is right,
hold what withstands, in 3-5 sentences.

Output STRICT JSON:
{"response": "...", "position_after": "conceded | narrowed | held",
 "score_adjustment": 0}
