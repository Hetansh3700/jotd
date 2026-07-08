---
type: project
title: Atlas
aliases: [atlas, atlas-api]
created: 2026-06-01
---
Backend API platform. Current focus: latency and rate limiting. PM is [[sarah-chen]].

## Log
- 2026-06-20: p99 SLO set to 250ms (cap-20260620-101500-a1b2)
- 2026-06-28: connection pooling fix merged (cap-20260628-113000-b7c8)
- 2026-07-07: atlas p99 latency dropped to 180ms after the connection pooling fix (cap-20260707-090500-00000005)
- 2026-07-07: the atlas rate limiter is moving to the gateway, backend team owns it now (cap-20260707-090700-00000007)
- 2026-07-07: we're killing the atlas graphql experiment, rest only from here (cap-20260707-090900-00000009)
- 2026-07-07: need to renew the atlas pagerduty rotation before end of month (cap-20260707-091500-0000000f)
- 2026-07-07: marcus is taking over atlas on-call from me starting next sprint (cap-20260707-092100-00000015)
- 2026-07-07: priya's design system audit is blocking the atlas admin ui refresh (cap-20260707-092300-00000017)

## Open loops
- [ ] write the atlas postmortem for the june 25 outage <!-- loop:cap-20260626-090000-d9e0 -->
- [ ] need to renew the atlas pagerduty rotation before end of month <!-- loop:cap-20260707-091500-0000000f -->
