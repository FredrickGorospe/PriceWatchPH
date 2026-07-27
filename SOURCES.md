# SOURCES.md

Governance record of data sources for PriceWatch PH. This document is not
research and contains no claims about what any third party's terms of service
say. Every field derived from a source's actual terms is marked `UNVERIFIED`
until a human reads the terms directly and records the finding, with the date
and who verified it. No `UNVERIFIED` field may be filled in by an LLM.

Sources are listed in priority order.

---

## 1. eBay API

- **Status:** UNDER REVIEW
- **Access method:** API
- **Terms of service URL:** TODO
- **What the terms say about automated access:** UNVERIFIED - read [URL] and record the clause here
- **What the terms say about storing and republishing prices:** UNVERIFIED - read [URL] and record the clause here
- **Rate limit chosen:** UNVERIFIED
- **Reason for that rate limit:** UNVERIFIED
- **Date verified, and by whom:** TODO
- **Kill criteria:** The API license terms prohibit storing or republishing derived price data, or no available access tier permits the PH-relevant query pattern at any acceptable rate.

---

## 2. My own 2018–present buy/sell records, entered manually

- **Status:** UNDER REVIEW
- **Access method:** manual entry
- **Terms of service URL:** N/A — first-party data, no external terms govern this source
- **What the terms say about automated access:** N/A — first-party data, no external terms govern this source
- **What the terms say about storing and republishing prices:** N/A — first-party data, no external terms govern this source
- **Rate limit chosen:** N/A — first-party data, no external terms govern this source
- **Reason for that rate limit:** N/A — first-party data, no external terms govern this source
- **Date verified, and by whom:** TODO
- **Kill criteria:** N/A — this source is first-party data with no external terms to violate; rejection criteria does not apply in the same sense as scraped sources.

---

## 3. TipidPC

- **Status:** UNDER REVIEW
- **Access method:** not yet determined
- **Terms of service URL:** TODO
- **What the terms say about automated access:** UNVERIFIED - read [URL] and record the clause here
- **What the terms say about storing and republishing prices:** UNVERIFIED - read [URL] and record the clause here
- **Rate limit chosen:** UNVERIFIED
- **Reason for that rate limit:** UNVERIFIED
- **Date verified, and by whom:** TODO
- **Kill criteria:** robots.txt or the terms of service explicitly disallow automated fetching, or listing access requires an authenticated session whose terms disallow bot use.

---

## 4. Carousell PH

- **Status:** UNDER REVIEW
- **Access method:** not yet determined
- **Terms of service URL:** TODO
- **What the terms say about automated access:** UNVERIFIED - read [URL] and record the clause here
- **What the terms say about storing and republishing prices:** UNVERIFIED - read [URL] and record the clause here
- **Rate limit chosen:** UNVERIFIED
- **Reason for that rate limit:** UNVERIFIED
- **Date verified, and by whom:** TODO
- **Kill criteria:** The terms of service prohibit scraping or automated access, or listing access requires authentication whose terms prohibit bot use.

---

## 5. Philippine retailer list prices (the "new" depreciation anchor)

- **Status:** UNDER REVIEW
- **Access method:** not yet determined
- **Terms of service URL:** TODO
- **What the terms say about automated access:** UNVERIFIED - read [URL] and record the clause here
- **What the terms say about storing and republishing prices:** UNVERIFIED - read [URL] and record the clause here
- **Rate limit chosen:** UNVERIFIED
- **Reason for that rate limit:** UNVERIFIED
- **Date verified, and by whom:** TODO
- **Kill criteria:** The specific retailer's terms prohibit automated price collection, or list prices are only available behind a login whose terms forbid bot use.

---

## 6. Manual paste-a-listing capture

- **Status:** APPROVED
- **Access method:** manual entry
- **Terms of service URL:** N/A — no automation involved, no external terms apply to this source
- **What the terms say about automated access:** N/A — no automation involved, no external terms apply to this source
- **What the terms say about storing and republishing prices:** N/A — no automation involved, no external terms apply to this source
- **Rate limit chosen:** N/A — no automation involved, no external terms apply to this source
- **Reason for that rate limit:** N/A — no automation involved, no external terms apply to this source
- **Date verified, and by whom:** TODO
- **Kill criteria:** N/A — no automation, no ToS exposure; rejection criteria does not apply.

---

## Excluded sources

### Facebook Marketplace

**Permanently excluded. Final. Not to be revisited.**

Reason: automated collection is prohibited by Meta's terms, and a portfolio
project whose core data source depends on a terms violation is not defensible
in an interview.
