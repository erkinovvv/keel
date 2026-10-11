# Journey eval — task completion on scripted client personas

Personas run: **30** (balanced across C1–C5; 6 in Chinese). Live model on Groq free tier.

**Full journeys completed: 29/30 (97%)**

| Check | Pass rate |
|---|---:|
| profile recorded | 100% |
| profile class correct | 97% |
| amount recorded | 100% |
| allocation built | 100% |
| allocation suitable | 100% |
| stress tested | 100% |
| answer not blocked | 100% |
| no crash | 100% |
| client language | 100% |
| concise | 100% |
| no promises | 100% |

Median tokens per journey: 10,753 · median LLM calls: 6 · median seconds: 115.0 · tool errors per journey: 0.0

| Persona | Lang | Expected | Got | Completed | Failed checks | Tokens |
|---|---|---|---|---|---|---:|
| P01 | en | C1 | C1 | ✅ | — | 10,005 |
| P02 | en | C2 | C2 | ✅ | — | 9,965 |
| P03 | en | C3 | C3 | ✅ | — | 9,864 |
| P04 | en | C4 | C4 | ✅ | — | 15,230 |
| P05 | zh | C5 | C5 | ✅ | — | 15,133 |
| P06 | en | C1 | C1 | ✅ | — | 9,995 |
| P07 | en | C2 | C2 | ✅ | — | 10,247 |
| P08 | en | C3 | C3 | ✅ | — | 9,897 |
| P09 | en | C4 | C3 | ❌ | profile_class_correct | 13,562 |
| P10 | zh | C5 | C5 | ✅ | — | 11,695 |
| P11 | en | C1 | C1 | ✅ | — | 10,037 |
| P12 | en | C2 | C2 | ✅ | — | 12,951 |
| P13 | en | C3 | C3 | ✅ | — | 15,062 |
| P14 | en | C4 | C4 | ✅ | — | 10,823 |
| P15 | zh | C5 | C5 | ✅ | — | 11,390 |
| P16 | en | C1 | C1 | ✅ | — | 10,636 |
| P17 | en | C2 | C2 | ✅ | — | 10,683 |
| P18 | en | C3 | C3 | ✅ | — | 9,920 |
| P19 | en | C4 | C4 | ✅ | — | 10,173 |
| P20 | zh | C5 | C5 | ✅ | — | 12,382 |
| P21 | en | C1 | C1 | ✅ | — | 9,913 |
| P22 | en | C2 | C2 | ✅ | — | 13,088 |
| P23 | en | C3 | C3 | ✅ | — | 10,068 |
| P24 | en | C4 | C4 | ✅ | — | 9,710 |
| P25 | zh | C5 | C5 | ✅ | — | 10,858 |
| P26 | en | C1 | C1 | ✅ | — | 10,096 |
| P27 | en | C2 | C2 | ✅ | — | 14,740 |
| P28 | en | C3 | C3 | ✅ | — | 15,018 |
| P29 | en | C4 | C4 | ✅ | — | 12,520 |
| P30 | zh | C5 | C5 | ✅ | — | 11,464 |
