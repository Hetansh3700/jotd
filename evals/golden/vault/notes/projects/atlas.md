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
- 2026-07-07: Scaling the write path remains the biggest capacity risk going into Q3. Current headroom is roughly 40% at peak; the proposal adds two read replicas per region and moves batch reindexing off-peak, pending platform review before the August freeze. (cap-20260707-093100-0000001f)
- 2026-07-07: devon 11:03 AM the atlas rate limiter cutover finished last night, gateway team owns the config now, p99 held at 181ms through the switch 🎉 3 replies Last reply today at 11:40 AM (cap-20260707-093200-00000020)
- 2026-07-07: checks.........................: 100.00% 4821 out of 4821 http_req_duration..............: avg=64.2ms p(95)=141ms p(99)=183ms http_req_failed................: 0.02% scenarios: search_burst ramping-vus target: https://atlas-api.internal/v2/search (cap-20260707-093400-00000022)

## Open loops
- [ ] write the atlas postmortem for the june 25 outage <!-- loop:cap-20260626-090000-d9e0 -->
- [ ] need to renew the atlas pagerduty rotation before end of month <!-- loop:cap-20260707-091500-0000000f -->
