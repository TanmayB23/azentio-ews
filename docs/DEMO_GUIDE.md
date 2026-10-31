# EWS: demo guide

For the team presenting to the judges. Contents:

1. [Demo script](#1-demo-script-about-10-minutes): what to click and say, plus answers to likely questions.
2. [Scoring parameters](#2-scoring-parameters): every setting the system uses to score customers.
3. [Do we use ML or AI?](#3-do-we-use-ml-or-ai): the honest answer and what could be added.

Customer IDs and numbers come from the India sample (`data/india`). They are the same on the clean and dirty versions.

---

## 1. Demo script (about 10 minutes)

### Before you start

- [ ] **Start the app:** `python -m api`, then open http://127.0.0.1:8000 in a full-screen browser at 100% zoom.
- [ ] **Set the analyst name:** in Settings, enter the name of whoever is presenting, so it appears on decisions.
- [ ] **Have a scored portfolio ready:** keep an *India sample (clean)* assessment loaded as a fallback. The live demo scores the *dirty* data.
- [ ] **Have the Gulf portfolio ready:** run a *GCC Islamic* assessment beforehand for the region switch in step 10.
- [ ] **Open a backup tab** on the watchlist of the clean run, in case live scoring is slow.
- [ ] **Hide the answer key:** close any `ground_truth.csv` file. It's for tests only and must never appear on screen.

### The flow through the product

```
 Data & validation ──► Run assessment ──► Overview ──► Watchlist ──► Customer ──► Analyst review
   (upload, check)      (score 500)       (portfolio    (who needs    (why the      (decide, keep
                                           at a glance)  attention)    score)        the evidence)
                                               │
                                               └──► Portfolio & clusters ──► Audit trail
                                                    (shared risk)            (every decision)
```

What each part does:

1. **Data & validation:** load CSV, Excel or JSON files. Each record is checked, linked to its customer and loan, and either kept, repaired or set aside.
2. **Run assessment:** scores every customer from 0 to 100 (higher = riskier). The result is saved as a permanent record that can't be edited.
3. **Overview:** exposure at risk, risk bands, review progress and emerging clusters.
4. **Watchlist:** customers to act on, with filters for product, segment, risk level, delinquency and portfolio.
5. **Customer:** why the score is what it is, signal by signal, with charts of the evidence.
6. **Analyst review:** record one of the four decisions from the brief with a reason. The original evidence is never changed.
7. **Portfolio & clusters:** groups of customers going wrong together.
8. **Audit trail:** every assessment and decision in order.

### Script

#### 1. Opening (30 s)

> "Most lenders only see trouble once a payment is missed. Our Early Warning System looks at how a customer's behaviour is changing over time: repayments, cash flow, borrowing and business health. It flags deterioration early, explains why, and gives analysts a defensible way to act on it."

#### 2. Loading and checking data (1 min 30 s)

**Do:** open **Data & validation**, then click **India · dirty**.

> "This is a 500-customer portfolio in seven tables, with errors deliberately added. Before anything is scored, every record is checked and linked to its customer and loan."

**Point at:**

- The four numbers: **51 issues, 18 rows set aside, 18 values repaired**.
- In the issues table, filter **Action → repaired**:
  > "A missing total inflow is recalculated from its parts. An amount written as '1,20,000' is read as a number. A misspelled customer type is corrected. Every fix is recorded."
- Under **Quarantined rows**, open **repayments**:
  > "Repayments for a loan that doesn't exist are set aside rather than guessed at."
- > "It accepts CSV, Excel or JSON, either uploaded here or as one file per table."

#### 3. Scoring (45 s)

**Do:** leave the region as **India (INR)** and click **Run assessment**.

> "Scoring takes about 20 seconds. Each customer is checked against 15 configurable signals, grouped into four areas: repayment, cash flow, exposure, and business health for SMEs. Thresholds and weights come from a configuration file, not the code, so the risk team can tune them."

If it takes longer than 30 seconds, switch to the backup tab.

#### 4. Overview (1 min)

**Do:** the app opens on **Overview** automatically.

> "Higher score means higher risk. ₹37.9 Cr of exposure sits with 96 High and Critical customers out of 500."

**Point at:**

- **Risk bands:** 60 Critical, 36 High, 25 Medium, 367 Low, and 12 Insufficient data.
  > "Customers without enough history get their own label. We never assume missing data means high risk."
- **Customers above each score:**
  > "This shows how big the watchlist gets at different score cut-offs."
- **Review progress** and **Emerging clusters:** mention them; we come back to clusters later.

#### 5. Watchlist (1 min)

**Do:** click **Open watchlist**, then **Risk band → Critical + High**, then **Not reviewed**.

> "This is the analyst's queue. Each row shows the customer, product, outstanding balance, score, band, the indicators driving it, days past due, how complete the data is, and monitoring status. It filters by product, segment, risk level, delinquency and portfolio, and the filtered view is a link you can share or export to CSV."

**Do:** search **C0009** and open **Gupta Textiles Traders**.

#### 6. The key story: warning before a payment is missed (1 min)

**C0009 · Gupta Textiles Traders · High, 71**

> "This customer is **0 days past due**. They've never missed a payment. A traditional system would see nothing. We rate them **High**: income has fallen **5 months in a row**, average inflows are **down 29%**, and there are **3 bounced transactions**."

**Point at:**

- **Score breakdown:** Cash flow is the problem area; Repayment is still 0.
- **Evidence over time → Cash flow:** the falling income line.

> "That's what an early warning means: we flag them while there's still time to act."

#### 7. Telling one-off problems from real deterioration (2 min)

Use the top search bar for each customer ID.

| Customer | What appears on screen | What to say |
|---|---|---|
| **C0040 Joshi Textiles & Sons** | Critical, 100. Delays of 10, then 19, then 53 days; latest instalment unpaid | "Delays getting longer each month, now 53 days past due. The roll-forward rule escalates them to Critical, and the reason is written on screen." Open **Repayments**: the red bars climb. |
| **C0046 Singh Retail & Sons** | Medium, 25 | "This one was also late for three months, but is now back on time. Recovering, not worsening, so Watch rather than Escalate." |
| **C0273 Neha Nair** | Low, 0 | "One payment was 19 days late because her employer paid her salary late, and there's evidence on file. Clean before, recovered after. That single event is treated as an exception, not as deterioration." |
| **C0003 Chawla Construction Industries** | Low, 18 | "Income is down 33%, which looks alarming. But it's −2% against the same months last year: a seasonal business. We compare like with like." |
| **C0001 Vikram Joshi** | Insufficient data, 45% confidence | "Only three months of history and no bank data. We say so plainly instead of calling them risky." |

#### 8. Analyst review (1 min)

**Do:** go back to **C0040**. Select **Escalate for Review**, type a reason, and click **Record decision**. Then select **Requires Investigation**, type a different reason, and record it.

> "Analysts choose from the four decisions in the brief, and a reason is required. Changing the decision adds a new entry; it never overwrites. The original score and evidence are stored once and the database refuses edits. Anyone can download the original alert as it was scored."

**Point at:** the **Decision history** with both entries, and **Original alert (JSON)**.

#### 9. Portfolio clusters (1 min)

**Do:** open **Portfolio & clusters**, then **Textiles · Tamil Nadu**.

> "Here the risk is shared, not individual. 13 of the 15 textile SMEs in Tamil Nadu score Medium or above, **3.5 times** the portfolio rate. What really stands out is the shared pattern: **12 of the 15 are taking longer to collect from their customers**, against 6.8% of the rest of the book. That's **11.8 times** more common, the ×11.8 on the card. That points to a sector problem, not 13 separate ones."

The card shows both figures: the ×11.8 sits next to "Receivable days rising: 12 of 15 vs 6.8% of the book", and the line below shows "13 of 15 Medium or above (×3.5)". Don't attach ×11.8 to the "13 of 15" figure.

Also mention:

- **Gig Economy · Karnataka (×3.8):** gig workers in one state whose income is dropping together. Inflows fell in 9 of 11, against 21% of the book.
- **Logistics & Transport (×5.6):** caught by a shared warning sign. 12 of 32 firms are collecting payments more slowly, against 6.8% of the book, even though only 17 of 32 score Medium or above.

#### 10. Audit trail and region switch (45 s)

**Do:** open **Audit trail**.

> "Every assessment and decision is kept, so a regulator or auditor can see what we knew and when."

**Do:** use the sidebar switcher to choose the **GCC Islamic** assessment.

> "The same engine runs a Gulf Islamic-finance portfolio. Amounts are in dirhams, and contract types such as Murabaha, Ijarah and Tawarruq appear on the data. The holiday calendar, scoring settings and minimum-score thresholds come from a region profile. It flags construction contractors in Dubai: 10 of 13 are collecting payments more slowly, against 5.1% of the book, which is 15 times more common. And 11 of the 13 score Medium or above."

#### 11. Close (20 s)

> "That covers every capability in the brief: ingestion and validation, early-warning signals, an explainable score, a filterable watchlist, and analyst review with preserved evidence. On top of that we added cluster detection, seasonal adjustment, roll-forward risk and region profiles."

### Questions judges may ask

| Question | Answer |
|---|---|
| Is this machine learning? | "It's rules plus statistics, and that's deliberate: every point in a score can be traced, which credit risk needs. Thresholds and weights are configurable, and the per-signal outputs could feed a model later." See [section 3](#3-do-we-use-ml-or-ai). |
| How do you know it works? | "We built a synthetic data generator with planted scenarios. Our tests check that no healthy customer is rated High, every thin-history customer comes out as Insufficient data, and every worsening delinquency case is Critical, across both regions." |
| Is the data real? | "It's synthetic data we generated to cover every scenario in the brief, plus traps like seasonality and late salaries. The answer key is used only in tests and never by the app." |
| What if data is missing? | "Signals without enough data are marked as missing and their weight is set aside. Confidence shows how much could be checked, and below 50% the customer gets Insufficient data instead of a risk level." |
| Can an analyst change a score? | "No. They record a decision and a reason. The original score and evidence are permanent." |
| What's missing for production? | "Single sign-on and roles, connections to the core banking system and credit bureau, and scheduled re-scoring. The architecture is ready for each of these." |

### If something breaks

- **Live scoring is slow:** switch to the backup tab.
- **A page shows a loading placeholder:** wait about one second.
- **The server stops:** restart it with `python -m api`. Data and assessments survive a restart.

---

## 2. Scoring parameters

The settings the system uses to score customers. They live in [config/risk_signal_definitions.json](../config/risk_signal_definitions.json) and [config/profiles/india.json](../config/profiles/india.json).

### 2.1 The 15 warning signals

Each signal is measured over a window of recent months. Its strength is 0 at the **trigger** value and rises to 1 at the **full** value. Points = weight × strength, and weights are relative, not percentages.

| ID | Signal | Fires when | Trigger → full | Weight |
|---|---|---|---|---|
| **Repayment** | | | | |
| RB01 | Late payment frequency | Late payments in 2+ of the last 6 months | 2 → 5 months | 15 |
| RB02 | DPD trend rising | Days past due rising by 1+ day per month | 1 → 6 days/month | 12 |
| RB03 | Partial payments | 1+ partially paid instalment in 6 months | 1 → 3 | 6 |
| RB04 | Current delinquency | An instalment is overdue now | 1 → 60 DPD | 14 |
| **Cash flow** | | | | |
| CF01 | Falling income | Income down month on month, totalling 10%+ | 1 → 4 months | 14 |
| CF02 | Inflow level drop | Last 3 months' average inflows vs the previous 3 | −10% → −35% | 6 |
| CF03 | Balance erosion | Last 3 months' average balance vs the previous 3 | −15% → −50% | 5 |
| CF04 | Spending more than earning | Outflows above inflows | 2 → 5 of 6 months | 3 |
| CF05 | Bounced transactions | Returned or bounced payments in 6 months | 1 → 4 | 4 |
| **Exposure** | | | | |
| EX01 | Utilisation rise | Credit line or card usage up over 6 months | +15 → +40 points | 8 |
| EX02 | New facilities | New loans or lines opened in 6 months (a new customer's first loan doesn't count) | 1 → 3 | 4 |
| EX03 | Debt growing faster than income | Obligations ÷ inflows rising | +5 → +20 points | 7 |
| EX04 | Credit inquiries | New credit applications in 90 days | 2 → 6 | 2 |
| **Business (SMEs only)** | | | | |
| SM01 | Tax filing problems | GST or VAT returns filed late or not at all | 1 → 4 | 6 |
| SM02 | Customers paying slower | Days to collect payment rising | +10 → +35 days | 6 |

Each signal also has a **minimum amount of data** (for example, CF02 needs all 6 months). Below that, the signal is marked "missing data", not risky. A signal that doesn't fit the customer is marked "not applicable", for example SM signals for individuals, or utilisation for someone with no credit card or credit line.

### 2.2 How the score is combined

| Setting | Value | Meaning |
|---|---|---|
| Area scores | 0–100 each | Repayment, Cash flow, Exposure, Business |
| Combination | 1.0 / 0.35 / 0.15 / 0.10 | Highest area counts in full; the next three add 35%, 15% and 10% |
| Area coverage | at least 50% | An area is scored only if half its signal weight has data |
| Score range | 0–100 | Higher = riskier |

### 2.3 Risk bands

| Band | Score | Monitoring status |
|---|---|---|
| Low | 0–24 | Routine |
| Medium | 25–49 | Watch |
| High | 50–74 | Investigate |
| Critical | 75–100 | Escalate |
| Insufficient data | — | Collect data |

### 2.4 Adjustments

| Rule | When it applies | Effect |
|---|---|---|
| **Temporary missed payment** | One late month (delays of 3 days or less are ignored), at least 3 clean months before, back on time within 2 instalments | Repayment signals ×0.25 with evidence, ×0.6 without |
| **Seasonality** | 15+ months of history, and the last 3 months' income is no more than 5% below the same months last year | Falling-income signals ×0.3 |
| **Holiday exception** | Due date on a weekend or bank holiday, paid within 3 days | Treated as an exception with evidence |
| **Roll-forward risk** | Latest instalment unpaid, after 2+ late payments in the previous 3 with delays not shrinking (or earlier instalments also unpaid) | Score raised to at least 75 (Critical) |
| **Recent delinquency episode** | 3+ late months in 6, worst delay 10+ days | Score raised to at least 25 (Medium) |

### 2.5 Missing data

| Setting | Value |
|---|---|
| Minimum repayment history | 4 months |
| Minimum confidence | 50% of applicable signal weight evaluated |
| Below either | "Insufficient data": no score, no band |
| Rule | Missing data never adds risk points |

### 2.6 Cluster detection

| Test | Threshold |
|---|---|
| Elevated-risk cluster | Group's share of Medium-or-above customers at least 1.5× the portfolio rate, p ≤ 0.001 |
| Shared-signal cluster | Same signal active at least 2.5× the portfolio rate, p ≤ 0.0001 |
| Minimum group | 5 customers, at least 4 hits |
| Groupings | Industry × region, industry, region, segment, portfolio, main product |

The ×N shown on a cluster is the lift from whichever test flagged it: the share of customers with the named pattern in the group, divided by its share across the book. The card names the pattern and shows both shares, and the elevated-risk lift is shown separately.

### 2.7 Region profile settings

| Setting | India | GCC Islamic |
|---|---|---|
| Currency | INR | AED |
| Weekend | Sunday | Saturday–Sunday |
| Holiday grace | 3 days | 3 days |
| Debt burden cap | — | 50% (configured, but no signal uses it yet) |

### 2.8 Changing them

- **Signals:** edit `config/risk_signal_definitions.json`.
- **Scoring rules:** edit `config/profiles/<region>.json`.
- **Per upload:** include a `risk_signal_definitions.csv` with the data. Its trigger, saturation and weight values override the defaults for that upload only.

No code changes are needed. A new assessment uses the new values, and earlier assessments keep the settings they were scored with.

The cluster thresholds in 2.6 are the exception: they're currently fixed in the code ([ews/engine/clusters.py](../ews/engine/clusters.py)), not in the config files.

---

## 3. Do we use ML or AI?

**No. Right now it uses neither machine learning nor AI.** It runs on configurable rules plus basic statistics:

| Where | Technique |
|---|---|
| Signals | Rule thresholds (trigger → full strength) on measures taken over time |
| DPD trend (RB02) | Linear regression slope across recent months |
| Cash flow (CF01–CF03) | Consecutive-decline runs and comparisons of 3-month averages |
| Seasonality | Same months this year vs last year |
| Clusters | One-sided binomial significance tests with lift |
| Scoring | Weighted combination of the four risk areas, plus override rules |

**Is that acceptable for the brief?** The brief allows it: detection may use "configurable rules, statistical analysis, machine learning or a combination". So the app meets the requirements as written. But the brief also says "AI-powered Early Warning System", the category is "AI for Credit Risk Intelligence", and it gives extra credit for predictive techniques. Judges will likely ask this, so the honest answer for now is: "rules plus statistics, chosen so every point is explainable".

**One real gap:** the brief asks the system to "recommend timely interventions" and say "what actions may be appropriate". We only give a monitoring status (Watch / Investigate / Escalate), not a recommended action.

### What we could add, in order of value

1. **Recommended actions (AI-assisted). Closes the gap above.** A rule-based playbook maps each situation to concrete actions:
   - roll-forward risk → collections contact within 7 days;
   - falling cash flow → relationship manager call and restructuring review;
   - rising exposure → freeze limit increases.

   Then Claude writes a short case note and action plan for each alert, using **only** that alert's signals and evidence. That makes it explainable, it can't invent facts, and the analyst stays the decision-maker.
2. **Predicted chance of serious delinquency (ML).** A gradient-boosting model predicts the probability that a customer reaches 30+ DPD within the next 3 months. It's trained on the monthly history using the same signal values as features, shown next to the rule score with the factors that drove it. One caution: our data is synthetic, so the model would partly learn our generator's patterns. Present it as "the method, ready for real data", not as proof of accuracy.
3. **Unusual-behaviour detection (ML).** An isolation forest over each customer's monthly behaviour flags patterns no rule anticipated, as an extra "unusual behaviour" signal with low weight.

**Recommendation:** build 1 first, because it closes a stated requirement and is the most visible "AI" for the judges. Add 2 if there's time; it covers "delinquency prediction" from the brief's focus list.
