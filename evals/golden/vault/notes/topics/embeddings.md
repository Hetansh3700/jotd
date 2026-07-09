---
type: topic
title: Embeddings
aliases: [embedding, vector search]
created: 2026-06-10
---
Notes on embedding models and local vector search.

## Log
- 2026-06-10: bge-small-en-v1.5 is good enough for note-scale retrieval, 384 dims, runs local
- 2026-07-07: idea: the embeddings dedupe pass could also power a related-notes sidebar (cap-20260707-091000-0000000a)
- 2026-07-07: As the corpus grows, near-duplicate vectors begin to dominate nearest-neighbor results. Adding a periodic dedupe pass over the embedding space - clustering at cosine similarity above 0.97 and keeping one centroid per cluster - restored recall@10 by 14 points on our internal benchmark. Sign up for our newsletter Subscribe 47 comments Share (cap-20260707-092900-0000001d)
