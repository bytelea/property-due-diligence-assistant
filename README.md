# Property Scan

> **A clearer view of what matters.**

**More than documents. Real answers.**

Property Scan is an AI-supported property due diligence web app for residential buyers. It analyzes multiple property documents together, surfaces contradictions, missing evidence and financial risks, and turns them into evidence-backed findings and concrete next steps.

Built during the **AI.WOMEN Hackathon 2026**.

**Trust / Evidence / Clarity**

---

## Live Demo

**Frontend:**  
https://propertyscan.lovable.app

**Backend API:**  
https://property-due-diligence-api-267668658542.europe-west1.run.app

**Interactive API Docs:**  
https://property-due-diligence-api-267668658542.europe-west1.run.app/docs

---

## The Problem

Buying a property often means reviewing a large package of documents:

- property listings
- floor plans
- homeowners' association minutes
- annual statements
- economic plans
- land-register extracts
- energy certificates
- rental agreements
- tax documents
- planning and compliance documents

For a non-expert buyer, the difficult part is not simply reading them.

The real questions are:

- Do the documents contradict each other?
- Are there hidden or upcoming costs?
- Is important evidence missing?
- What should I clarify before signing?

Most tools summarize documents one by one.

**Property Scan cross-checks them as one property.**

---

## What We Built

```text
Property PDFs
    ↓
Anymize — OCR + anonymization
    ↓
AI — structured fact extraction
    ↓
Canonical normalization
    ↓
Deterministic rule engine
    ↓
Property Assessment
    ↓
Summary → Detailed Evaluation → Action List
````

Property Scan is designed to keep every important finding connected to its source evidence.

The goal is not simply to summarize documents.

The goal is to answer:

> **What could I regret after signing?**

---

## Example Findings

### Floor-area conflict

**Listing:** 105 m²
**Floor plan:** 92 m²

Property Scan identifies the discrepancy only when the measurements are actually comparable and keeps both sources visible.

**Buyer action:** Ask which floor-area figure is legally recognised and request supporting documentation.

---

### Upcoming contribution

**€6,500** documented as an upcoming unit-level contribution.

Property Scan distinguishes a unit amount from a building-wide project total and avoids assuming who must pay when responsibility is unresolved.

**Buyer action:** Clarify the payment amount, due date and whether the seller or buyer is responsible.

---

### Missing planning evidence

An alteration is referenced, but supporting planning or compliance evidence is missing.

Property Scan reports **evidence missing / needs verification** rather than claiming the alteration is illegal.

**Buyer action:** Request the relevant planning or compliance documents before proceeding.

---

## How AI Is Used

AI is used where understanding unstructured property documents is necessary:

* document classification
* structured fact extraction
* German-language property-document understanding
* evidence capture from anonymized text

The AI does **not** make the final due-diligence decision on its own.

> **AI reads the documents. Our rule engine cross-examines the facts.**

After extraction, the backend normalizes the information and applies deterministic property rules.

This makes the system easier to test, explain and improve.

---

## Evidence-First Analysis

A material finding can be traced through:

```text
PropertyAssessment
        ↓
Finding
        ↓
RuleEvaluation
        ↓
Triggering PropertyFact
        ↓
Source document / page / evidence
```

The backend deliberately preserves distinctions such as:

* living area ≠ tax area
* project total ≠ unit liability
* planned expenditure ≠ historical actual expenditure
* missing evidence ≠ non-compliance
* works completed ≠ contribution paid

Unknown information stays unknown rather than being guessed.

---

## Product Experience

Property Scan focuses on three core screens.

### 1. Summary / Assessment

A quick view of:

* Critical
* Attention
* Positive
* Verify

plus the most important financial implications.

The goal is to help the buyer understand the property in the first few seconds.

---

### 2. Detailed Evaluation

Findings are grouped into themes such as:

* Property details
* Finances & homeowners' association
* Building & condition
* Energy
* Legal & ownership
* Tenancy
* Documents & completeness

Users can drill into:

* evidence
* conflicting values
* financial impact
* why a finding matters
* recommended next steps

---

### 3. Action List

Findings become concrete next steps.

Examples include:

* ask the seller or agent
* request missing documents
* clarify payment responsibility
* ask homeowners' association management
* verify information with a notary
* obtain a surveyor's assessment

The frontend can also track which actions have already been completed.

---

## Architecture

```text
┌──────────────────────────────────┐
│         Lovable Frontend         │
│                                  │
│ Upload                           │
│ Summary                          │
│ Detailed Evaluation              │
│ Action List                      │
└────────────────┬─────────────────┘
                 │
                 │ HTTPS
                 ▼
┌──────────────────────────────────┐
│        Google Cloud Run          │
│          FastAPI API             │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│             Anymize              │
│                                  │
│ OCR                              │
│ Anonymization                    │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│     Structured AI Extraction     │
│                                  │
│ anonymized text                  │
│ → PropertyFact[]                 │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│      Canonical Normalization     │
│                                  │
│ scope                            │
│ measurement type                 │
│ financial semantics              │
│ dates / status                   │
│ provenance                       │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│    Deterministic Rule Engine     │
│                                  │
│ RuleEvaluation[]                 │
│ conflicts                        │
│ missing evidence                 │
│ financial exposure               │
└────────────────┬─────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│        PropertyAssessment        │
│                                  │
│ findings                         │
│ evidence                         │
│ financial impact                 │
│ buyer actions                    │
└──────────────────────────────────┘
```

---

## Canonical Property Facts

Before rules are applied, extracted facts are normalized into a canonical property model.

This prevents different concepts from being compared incorrectly.

For example:

```text
Living area
≠
Tax area

Project total
≠
Unit liability

Planned expenditure
≠
Historical actual expenditure

Missing evidence
≠
Non-compliance
```

The normalization layer preserves important semantics such as:

* measurement type
* scope
* entity identity
* financial amount type
* payer or liability party
* recurring versus one-time amounts
* planned versus actual status
* document dates
* factual periods
* source authority
* evidence provenance

Unknown values remain unknown rather than being filled with assumptions.

---

## Deterministic Rule Engine

The due-diligence engine is based on a structured Rulebook developed by the team.

The rule architecture follows:

```text
Inputs
  ↓
Calculation
  ↓
Threshold / policy
  ↓
Rule result
  ↓
Finding
  ↓
Evidence
  ↓
Buyer action
```

The backend distinguishes between different evaluation states:

```text
NOT_APPLICABLE
MISSING_INPUTS
EVALUATED_PASS
TRIGGERED
```

This matters because:

> **"We do not have enough information" is not the same as "we checked this and everything is fine."**

Technical processing success is also kept separate from property decision readiness.

---

## Privacy & Security

Property documents may contain sensitive personal information.

Property Scan is designed so that:

* documents are anonymized before downstream AI extraction
* API secrets are stored in **Google Cloud Secret Manager**
* real API keys are never intentionally committed to GitHub
* downstream rule evaluation works on anonymized, structured property facts
* missing information is not silently inferred
* provider errors are sanitized before being returned to users

---

## Tech Stack

| Layer            | Technology                                                          |
| ---------------- | ------------------------------------------------------------------- |
| Frontend         | Lovable, React, TypeScript                                          |
| Backend          | Python, FastAPI, Pydantic                                           |
| Cloud            | Google Cloud Run, Cloud Build, Secret Manager                       |
| Document privacy | Anymize                                                             |
| Analysis         | Structured extraction, canonical normalization, deterministic rules |
| Deployment       | GitHub → Cloud Build → Cloud Run                                    |

---

## Current MVP

The current backend includes:

* multi-PDF upload
* PDF validation
* Anymize OCR/anonymization integration
* structured property-fact extraction
* canonical normalization
* deterministic rule evaluation
* evidence traceability
* financial-impact handling
* buyer actions
* frontend adapter contract
* production CORS configuration
* live Google Cloud deployment

At the latest verified backend milestone:

**137 automated tests are passing.**

Current integration work focuses on:

* live model-provider validation
* final production rule-policy values
* live Lovable upload → backend analysis connection
* Golden Case end-to-end validation

---

## API

### Health Check

```http
GET /health
```

Confirms that the backend service is running.

---

### Demo Assessment

```http
GET /demo-assessment
```

Returns a synthetic assessment used for frontend integration and testing.

---

### Single Document Analysis

```http
POST /analyze
```

Processes an individual PDF through the document-processing pipeline.

---

### Multi-Document Property Analysis

```http
POST /properties/analyze
```

This is the main property-analysis endpoint.

It accepts multiple PDFs using `multipart/form-data`.

Each document is uploaded using the repeated field name:

```text
files
```

Example:

```text
files = listing.pdf
files = floor-plan.pdf
files = management-minutes.pdf
files = energy-certificate.pdf
```

The backend analyzes the documents together and returns one structured `PropertyAssessment`.

---

## Frontend / Backend Integration

The frontend and backend were developed independently and communicate through an explicit API contract.

The frontend uses an adapter layer:

```text
Backend PropertyAssessment
          ↓
Frontend adapter
          ↓
OverallAssessment
AnalysisCluster[]
Insight[]
Action[]
FinancialOverview
          ↓
Existing UI components
```

This allows the backend due-diligence model and the frontend presentation model to evolve independently.

---

## Deployment

The backend is continuously deployed from GitHub.

```text
VS Code / Codex
      ↓
GitHub main
      ↓
Google Cloud Build
      ↓
Google Cloud Run
      ↓
Live FastAPI API
```

The frontend is hosted through Lovable.

```text
User
 ↓
https://propertyscan.lovable.app
 ↓
Lovable frontend
 ↓
Google Cloud Run API
 ↓
PropertyAssessment
 ↓
Summary / Details / Actions
```

---

## Brand System

Property Scan is built around three principles:

> **Trust / Evidence / Clarity**

### Colors

| Role               | Color     |
| ------------------ | --------- |
| Ink — Primary      | `#17242B` |
| Ivory — Background | `#F5F2EA` |
| Sage — Success     | `#9BAE9F` |
| Ochre — Attention  | `#D39A3A` |
| Brick — Critical   | `#B85C52` |
| Slate — Neutral    | `#718087` |

### Typography

* **Playfair Display** — headlines and emphasis
* **Inter** — body copy and UI text

### Brand Line

> **A clearer view of what matters.**

---

## Golden Case

The backend is tested against a defined Golden Case and adversarial scenarios.

The Golden Case helps identify whether an incorrect result was caused by:

* extraction failure
* normalization failure
* rule failure
* missing evidence
* policy or reasoning gap

This allows the team to test not only whether the final result is correct, but also **where the system failed if it is not**.

---

## Team

* **Alina** — Frontend + Team Lead
* **Julia** — Rulebook + Testing
* **Virginia** — UX + Customer Journey
* **Natascha** — Pitch + Storytelling / Brand
* **Lea** — Backend + AI

---

## What Makes Property Scan Different

Property Scan is not simply:

> Upload PDFs and receive summaries.

The product is designed around:

```text
Documents
    ↓
Evidence-backed facts
    ↓
Cross-document comparison
    ↓
Conflicts / risks / unknowns
    ↓
Financial implications
    ↓
Buyer actions
```

The system is deliberately explicit about uncertainty.

If evidence is missing, it says evidence is missing.

If two documents disagree, it shows both values.

If a cost is possible rather than documented, it remains possible.

If payer responsibility is unknown, the system does not silently assign it to the buyer.

---

## Disclaimer

Property Scan is a hackathon prototype and decision-support tool.

It does not provide legal, financial, tax, surveying or other professional real-estate advice.

Findings depend on:

* the documents supplied
* available evidence
* extraction quality
* normalization logic
* implemented rule definitions

Important conclusions should be independently verified before making a property-purchase decision.

---

## AI.WOMEN Hackathon 2026

Built with a focus on:

**Trust / Evidence / Clarity**

> **Property Scan — A clearer view of what matters.**
