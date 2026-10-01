# Evidence-Based Time Investment Model

## 1. Core Axiom

> **AI processing time is NOT user active time.**
> **A WhatsApp message timestamp does NOT prove continuous foreground screen attention.**
> **Delivering an AI response does NOT prove reading duration.**

The Personal Digital History Platform enforces strict epistemic integrity. No metric may be claimed without concrete telemetry backing it.

---

## 2. Telemetry Evidence Levels

| Level | Definition | Example |
|---|---|---|
| **PROVEN** | Directly and undeniably established by underlying telemetry. | Exact timestamp of prompt submission; moment of message transmission; AI execution completion. |
| **SUPPORTED** | Strongly supported by multiple independent correlative signals, but not directly measured. | User sends follow-up prompt referencing an error; proves comprehension occurred, but exact reading duration remains unmeasured. |
| **ESTIMATED** | Mathematically or model-estimated from incomplete signals. | Estimating 30 seconds for drafting a 100-word prompt without keystroke logging. |
| **UNKNOWN** | Insufficient evidence to establish what occurred. | Gaps between AI response delivery and next prompt; phone screen status between messages. |

---

## 3. The Five Independent Timelines

```text
[ Timeline 1: User Input ]         * (10:00:00)                               * (10:25:00)
[ Timeline 2: AI Processing ]      |============ (10:00 - 10:15) ===|
[ Timeline 3: Reading / Review ]   [ UNKNOWN ]                                [ UNKNOWN ]
[ Timeline 4: External App ]                    * (10:07)        * (10:18)
[ Timeline 5: Unknown Gap ]                     |........................|
```

1. **User Input Time**:
   - Discrete moments of interaction ($T_{submit}$).
   - Typing duration is **UNKNOWN** unless keypress start/end telemetry exists.
2. **AI Processing / Waiting Time**:
   - Measured with exact precision ($T_{reply} - T_{request}$).
   - Overlapping parallel agent tasks are merged via **Interval Union** to prevent double counting.
3. **Reading / Review Time**:
   - Only counted if direct focus/gaze/scroll telemetry exists.
   - Without direct telemetry, strictly reported as:
     `Reading time cannot be directly measured with current telemetry (UNKNOWN)`.
4. **External App Time**:
   - Message timestamps establish discrete communication events.
   - Continuous foreground usage requires OS-level `UsageStats` / `MOVE_TO_FOREGROUND` events. Without them, continuous duration is **UNKNOWN**.
5. **Unknown Time**:
   - All intervals between proven signals.

---

## 4. Interval Union Algorithm

Given a set of time intervals $I = \{[s_1, e_1], [s_2, e_2], \dots, [s_n, e_n]\}$:

$$\text{Union}(I) = \bigcup_{i=1}^n [s_i, e_i]$$

The total attributable time $T_{total}$ is the sum of lengths of the connected components of $\text{Union}(I)$:

$$T_{total} = \sum_{k=1}^m (e'_k - s'_k)$$

Where each $[s'_k, e'_k]$ is a disjoint merged interval.

**Guarantee**: $T_{total} \le \sum (e_i - s_i)$. Overlapping parallel activities (e.g. YouTube agent generating while Frappe script compiles) are never double-counted.
