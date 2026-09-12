# Property Due Diligence Assistant

> AI that cross-checks property documents so buyers can see what does not add up before they buy.

Built during the **AI.WOMEN Hackathon 2026** in Hamburg.

## The Problem

Property buyers receive a large number of documents before purchasing a home, including property listings, floor plans, management documents, energy certificates and legal or planning documents.

Most buyers are not property experts.

Important information may be:

- spread across different documents
- inconsistent between documents
- difficult to understand
- hidden inside long PDFs
- financially significant
- missing entirely

A normal document summary does not solve this problem.

Buyers need to know:

**What matters? What conflicts? What is missing? What could cost me money? And what should I ask before I buy?**

## Our Solution

The Property Due Diligence Assistant analyses multiple property documents together rather than summarising them independently.

The system:

1. anonymizes sensitive document data
2. extracts structured property facts
3. keeps source evidence for extracted facts
4. normalizes facts across documents
5. compares related facts
6. detects contradictions
7. detects missing information
8. identifies evidence-backed risks and positive signals
9. identifies known and potential financial implications
10. turns findings into concrete buyer actions

The final result is one evidence-backed **Property Assessment**.

## Example

Instead of returning:

> "The apartment has approximately 100 m²."

our system can identify:

### ⚠️ Floor Area Conflict

**Property listing:** 105 m²  
**Floor plan:** 92 m²  
**Difference:** 13 m²

**Why it matters**

The advertised floor area does not match the supplied floor-plan documentation.

**Evidence**

- Estate Agent Listing — `105 m²`
- Floor Plan — `Total internal area: 92 m²`

**Buyer action**

Ask the agent which floor-area figure is legally recognised and request supporting documentation.

---

### ⚠️ Upcoming Cost

**€6,500**

Management documents identify an upcoming works contribution that may create an additional cost for the buyer.

**Buyer action**

Confirm whether the €6,500 contribution will be paid by the current owner or the purchaser.

---

### ❓ Missing Planning Documentation

An alteration or extension is referenced, but supporting planning documentation has not been supplied.

The system does **not** assume that the alteration is compliant.

**Buyer action**

Request planning permission and/or relevant compliance documentation before proceeding.

## Core Product Flow

```text
PROPERTY DOCUMENTS
        ↓
DATA ANONYMIZATION
        ↓
DOCUMENT EXTRACTION
        ↓
STRUCTURED PROPERTY FACTS
        ↓
SOURCE EVIDENCE
        ↓
CROSS-DOCUMENT COMPARISON
        ↓
RULE + AI ANALYSIS
        ↓
RISKS / CONFLICTS / UNKNOWNS / POSITIVES
        ↓
FINANCIAL IMPACT
        ↓
BUYER ACTIONS
        ↓
PROPERTY ASSESSMENT
