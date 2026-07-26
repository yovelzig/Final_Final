---
document_id: "kb-en-003"
title: "Interest and Compound Interest"
slug: "interest-and-compound-interest"
version: 1
language: "en"
difficulty:
  - "beginner"
content_type: "educational_reference"
jurisdiction: "general"
review_status: "approved_seed"
collection: "finquest_core_financial_education"
concept_ids:
  - "principal"
  - "interest_rate"
  - "simple_interest"
  - "compound_interest"
  - "compounding_frequency"
  - "annual_percentage_rate"
  - "effective_annual_rate"
  - "annual_percentage_yield"
  - "present_value"
  - "future_value"
  - "fee_drag"
  - "debt_compounding"
  - "investment_compounding"
lesson_ids: []
source_policy: "authoritative_and_educational"
created_at: "2026-07-26"
reviewed_at: "2026-07-26"
requires_periodic_review: true
---

# Interest and Compound Interest

> **Educational scope:** This document explains general financial concepts. It does not provide personalized investment advice, recommend a security, or guarantee a return. APR, APY, fee disclosures, tax treatment, and lending rules vary by product and jurisdiction.

## Learning Objectives

- Define principal, interest rate, period, and compounding frequency.
- Calculate simple interest and periodically compounded future value.
- Distinguish nominal annual rate, effective annual rate, APY, and APR.
- Calculate present value and future value in basic fixed-rate examples.
- Explain how time, fees, deposits, withdrawals, and changing rates affect results.
- Compare debt compounding with investment or deposit compounding.
- Recognize when a formula is a simplified model rather than a product disclosure or return guarantee.

## Prerequisite Knowledge

The learner should understand percentages and basic exponents. A calculator may be used.

## Core Concepts

### Principal

Principal is the starting amount borrowed, deposited, or invested. It is the balance to which an interest rate is initially applied.

**Question to ask:** Does the principal change because of payments, deposits, withdrawals, fees, or capitalized interest?

**Limitation:** A real account can have a different principal on every day of a calculation period.

### Interest rate

An interest rate states the cost of borrowing or the compensation credited for the use of money over a defined period. A rate is incomplete unless its period and calculation method are known.

**Question to ask:** Is the rate annual, monthly, daily, fixed, variable, nominal, or effective?

**Limitation:** A stated interest rate may not include every fee or reflect the timing of all cash flows.

### Simple interest

Simple interest is calculated only on the original principal. In the basic model, previously calculated interest is not added to principal for later interest calculations.

**Question to ask:** Is interest paid out separately, or is it added to the balance?

**Limitation:** Many deposit and credit products do not follow a simple-interest model for their entire term.

### Compound interest

Compound interest is interest calculated on principal plus interest that was previously added to the balance. The balance therefore changes the base for later calculations.

**Question to ask:** When is accrued interest credited or capitalized?

**Limitation:** Compounding mathematics does not guarantee an investment gain because market value, fees, taxes, and withdrawals can offset growth.

### Compounding frequency

Compounding frequency is the number of times interest is added to the balance during a year or other stated period. Common examples include annual, monthly, and daily compounding.

**Question to ask:** Does the product compound at the same frequency used in the comparison?

**Limitation:** More frequent compounding helps only when the compared nominal rate and other terms remain the same.

### Annual percentage rate

APR is an annualized measure used to describe the cost of credit. In United States consumer disclosures, its exact calculation and included finance charges depend on the product and applicable rules.

**Question to ask:** Is the comparison APR-to-APR for similar products, and which fees are included?

**Limitation:** APR is not automatically the same as an effective annual growth rate, and rules vary by jurisdiction and credit product.

### Effective annual rate

The effective annual rate is the one-year rate that reflects within-year compounding under a stated mathematical model. It converts a nominal annual rate and compounding frequency into one comparable annual result.

**Question to ask:** Are the nominal rate, frequency, and assumption of no intervening cash flows clearly stated?

**Limitation:** The formula does not include fees, taxes, variable rates, deposits, or withdrawals unless the model adds them explicitly.

### Annual percentage yield

APY is an annualized deposit-account yield that reflects interest and compounding under the applicable disclosure assumptions. In a basic fixed-rate model, it can resemble an effective annual rate, but a real disclosed APY follows product and regulatory rules.

**Question to ask:** What balance, term, compounding method, and transaction assumptions are used?

**Limitation:** A disclosed APY may assume funds remain on deposit and may not represent the result after withdrawals, taxes, or every fee.

### Present value

Present value is the amount today that is mathematically equivalent to a future amount under a selected periodic rate and number of periods.

**Question to ask:** Why is the selected rate appropriate for this comparison?

**Limitation:** Present value changes when the assumed rate, timing, certainty, or cash-flow amount changes.

### Future value

Future value is the modeled amount that a present balance may become after applying stated rates and compounding rules over time.

**Question to ask:** Are later contributions, withdrawals, fees, and rate changes included?

**Limitation:** Future value is conditional on assumptions and is not a promised investment result.

### Fee drag

Fee drag is the reduction in an ending balance or return caused by charges. The effect depends on fee amount, timing, frequency, and whether the fee also reduces money available to compound.

**Question to ask:** Is the fee charged upfront, periodically, as a percentage, or at the end?

**Limitation:** Subtracting a fee only at the end is correct only when that timing matches the example.

## Detailed Explanation

### Simple-interest formulas

For the basic simple-interest model:

**I = P × r × t**

- **I** is the dollar amount of interest.
- **P** is original principal.
- **r** is the annual simple interest rate written as a decimal.
- **t** is time in years.

The ending amount is:

**A = P + I**

- **A** is principal plus accumulated simple interest.

Rate and time units must match. Six months is 0.5 years when **r** is annual. If the rate is monthly, the number of periods must also be expressed in months.

### Periodically compounded future value

For a fixed nominal annual rate compounded in equal periods:

**FV = P × (1 + r_nom / n)^(n × t)**

- **FV** is future value.
- **P** is starting principal.
- **r_nom** is the nominal annual rate as a decimal.
- **n** is compounding periods per year.
- **t** is time in years.
- **n × t** is total compounding periods.

This formula assumes the rate and frequency stay fixed and that no deposits, withdrawals, taxes, or fees occur. Recurring contributions require a cash-flow schedule or an annuity formula because each contribution compounds for a different number of periods.

### Effective annual rate and APY

For the same simplified fixed-rate model, the effective annual rate is:

**EAR = (1 + r_nom / n)^n − 1**

- **EAR** is effective annual rate as a decimal.
- **r_nom** is nominal annual rate as a decimal.
- **n** is compounding periods per year.

A 6% nominal annual rate compounded monthly produces an EAR of about 6.17%, not exactly 6%, because interest is added during the year. APY is also an annualized measure that reflects compounding for deposit accounts, but a disclosed APY follows the assumptions and calculation rules applicable to that account. Do not replace an official APY or APR disclosure with a homemade calculation.

### Present value and future value

When one periodic rate **i** applies for **m** periods:

**FV = PV × (1 + i)^m**

**PV = FV / (1 + i)^m**

- **PV** is present value.
- **FV** is future value.
- **i** is the rate per period as a decimal.
- **m** is the number of periods.

These formulas are inverse operations. The selected rate is an assumption that determines the comparison. It can represent a deposit rate, borrowing cost, required return, or another decision rate only when that interpretation is explicitly justified.

### Fees and cash-flow timing

A fee reduces the amount available to the learner, but there is no single universal fee formula. An upfront fee can reduce starting principal. A periodic fee can reduce the balance repeatedly and therefore reduce later compounding. A fee charged at the end can be subtracted from gross ending value in that specific example. Comparisons must use the actual timing and basis of each fee.

A useful schedule lists every date, beginning balance, interest calculation, contribution, withdrawal, fee, and ending balance. This is safer than forcing a complex product into one simplified formula.

### Debt and investment compounding

Compounding is a mathematical mechanism rather than a promise of benefit. On a deposit, credited interest can increase the balance used for later interest. On debt, unpaid interest may be added or otherwise reflected in the amount on which later charges are calculated, depending on contract and law. Fees and missed payments can add further cost.

An investment does not normally grow at a fixed guaranteed rate merely because a compound-interest formula is used. Market returns vary and can be negative. Compound-return calculations describe what happened or model a scenario; they do not remove investment risk.

## Integrated Concept Review

### Rate labels answer different questions

A nominal annual rate states a yearly rate before within-year compounding is converted into one effective result. EAR translates that nominal rate and frequency into a one-year mathematical result. APY is a deposit yield disclosure that reflects compounding under applicable assumptions. APR is a credit-cost disclosure whose included charges and calculation rules depend on product and jurisdiction.

The labels should not be mixed. A deposit APY should be compared with another appropriate deposit APY. A loan APR should be compared with an APR for a similar form of credit, while also reviewing payment schedule, total dollars paid, variable-rate terms, and penalties.

### Fees must be placed on the timeline

Fees do more than reduce a headline percentage. An upfront fee can reduce principal before growth begins. A monthly fee can repeatedly reduce the compounding base. A final fee affects ending value but not earlier growth. Two products with the same rate can therefore have different outcomes.

The learner should never subtract every fee at the end merely for convenience unless that is when it is actually charged. A period-by-period schedule makes the assumption visible.

## Worked Examples

All amounts and outcomes below are hypothetical and demonstrate formulas only.

### Example 1: simple interest

A principal of **$1,000** earns **5% simple annual interest** for **3 years**.

**I = $1,000 × 0.05 × 3 = $150**

**A = $1,000 + $150 = $1,150**

The same $50 is added each year because interest is calculated only on original principal.

### Example 2: monthly compounding and effective annual rate

A deposit of **$1,000** has a **6% nominal annual rate**, compounded monthly for one year.

**FV = $1,000 × (1 + 0.06 / 12)^12 = $1,061.68**

**EAR = (1 + 0.06 / 12)^12 − 1 = 0.061678, or about 6.17%**

The example excludes fees, taxes, deposits, withdrawals, and rate changes.

### Example 3: present value

A learner compares a hypothetical **$1,200** amount due in **2 years** using an assumed **5% annual rate**.

**PV = $1,200 / 1.05^2 = $1,088.44**

The result does not say that 5% is guaranteed or appropriate for every decision. It shows the present amount that would grow to $1,200 under the assumption.

### Example 4: debt compounding without payments

A hypothetical debt balance of **$1,000** grows at **1.5% per month** for **3 months**, with no payment and no additional fee.

**Balance = $1,000 × 1.015^3 = $1,045.68**

Actual contracts may use daily balances, grace periods, minimum payments, fees, or rules different from this simplified example.

### Example 5: a fee charged at year-end

Use the monthly-compounding result from Example 2, but assume a **$10 fee is charged only at the end of the year**.

**Net ending balance = $1,061.68 − $10 = $1,051.68**

The net increase is $51.68, or about 5.17% of starting principal. A fee charged monthly or upfront would produce a different result because it would alter the compounding base earlier.

## Common Mistakes

- Entering 5 instead of 0.05 for a 5% rate.
- Mixing annual, monthly, and daily units.
- Comparing APR, APY, nominal rate, and EAR as though they were interchangeable.
- Using the compound formula when deposits or withdrawals occur without modeling their dates.
- Ignoring fee timing and subtracting every fee only at the end.
- Treating a modeled investment rate as a guaranteed return.
- Assuming a minimum debt payment reveals the total borrowing cost or payoff time.

## Common Misconceptions

### APY and APR are the same annual number

APY is associated with deposit yield and compounding, while APR is a measure of credit cost. Exact disclosures depend on product and jurisdiction.

### More frequent compounding always creates the best product

More frequent compounding increases the effective result only when nominal rate and other terms are held equal. A lower rate or higher fees can outweigh the frequency effect.

### Compound interest guarantees investment profit

A fixed-rate formula can model growth, but a market investment can lose value. Reinvestment does not eliminate price risk.

### Present value is an objective fact

Present value changes with the selected rate, timing, cash-flow certainty, and assumptions.

### A small fee does not matter over time

Recurring fees can reduce both the current balance and the amount available for later compounding.

## Practical Application

Use this educational checklist when comparing interest-bearing examples:

- Record principal and every dated cash flow.
- Write each rate as a decimal and label its period.
- Identify whether the rate is nominal, effective, APY, or APR.
- Record compounding or capitalization frequency.
- Confirm that rate and time units match.
- Place every fee on the date it is charged.
- Compare products using the same horizon and cash-flow assumptions.
- For debt, review payment schedule, total dollars paid, variable-rate terms, and fees.
- For investments, test lower and negative return scenarios.
- Preserve the formula and assumptions so another learner can reproduce the result.

## Knowledge Check

1. What is principal?
2. What is the simple-interest formula, and what does each variable mean?
3. What assumptions are built into the basic compound future-value formula?
4. How is effective annual rate calculated from a nominal annual rate and compounding frequency?
5. Why should APY and APR not be treated as interchangeable?
6. What is the relationship between present value and future value?
7. Why does fee timing matter?
8. What is different about debt compounding and investment-return modeling?
9. Why must rate and time units match?
10. Why is a cash-flow schedule useful when contributions or withdrawals occur?

## Knowledge Check Answers

1. **The starting amount borrowed, deposited, or invested.**
2. **I = P × r × t, where I is interest, P is original principal, r is annual simple rate as a decimal, and t is years.**
3. **A fixed rate and frequency, equal periods, and no deposits, withdrawals, fees, or taxes unless added separately.**
4. **EAR = (1 + r_nom / n)^n − 1.**
5. **APY describes deposit yield under disclosure assumptions, while APR describes credit cost under product and jurisdiction rules.**
6. **They are inverse calculations under the same periodic rate and number of periods.**
7. **A fee charged earlier reduces the balance available for later compounding.**
8. **Debt can grow through contractual interest and fees, while investment returns are uncertain and may be negative.**
9. **Using an annual rate with a monthly period count without conversion produces an incorrect result.**
10. **Each cash flow has a different date and therefore compounds for a different number of periods.**

## Key Takeaways

- Interest calculations require principal, rate, period, and timing.
- Simple interest uses original principal; compound interest uses an updated balance.
- Nominal rate, EAR, APY, and APR answer different comparison questions.
- Present value and future value depend on an explicitly selected rate.
- Fees, contributions, withdrawals, and variable rates must be placed on the timeline.
- Debt compounding can increase obligations; investment compounding is not a guaranteed return.
- Formulas are conditional models and should be preserved with their assumptions.

## Glossary

- **Principal:** Starting amount borrowed, deposited, or invested.
- **Interest:** Amount charged or credited for the use of money.
- **Periodic rate:** Rate applied during one calculation period.
- **Simple interest:** Interest calculated only on original principal.
- **Compound interest:** Interest calculated on principal plus previously added interest.
- **Nominal annual rate:** Stated yearly rate before converting within-year compounding into an effective result.
- **Compounding frequency:** Number of times interest is added during a stated period.
- **EAR:** Effective annual rate under a stated mathematical compounding model.
- **APY:** Annualized deposit yield reflecting interest and compounding under applicable disclosure assumptions.
- **APR:** Annualized measure of credit cost under applicable product and legal rules.
- **Present value:** Current equivalent of a future amount under a selected rate.
- **Future value:** Modeled future amount under stated rate and cash-flow assumptions.
- **Capitalization:** Addition of accrued interest or charges to a balance used for later calculations.
- **Fee drag:** Reduction in balance or return caused by charges.

## References and Further Reading

- Federal Deposit Insurance Corporation — Chapter 5: Compound Interest: https://www.fdic.gov/consumer-resource-center/chapter-5-compound-interest
- Consumer Financial Protection Bureau — How does compound interest work?: https://www.consumerfinance.gov/ask-cfpb/how-does-compound-interest-work-en-1683/
- Investor.gov — Compound Interest Calculator: https://www.investor.gov/financial-tools-calculators/calculators/compound-interest-calculator
- Consumer Financial Protection Bureau — Regulation DD, Annual Percentage Yield definition: https://www.consumerfinance.gov/rules-policy/regulations/1030/2/
- Consumer Financial Protection Bureau — Regulation DD, Appendix A, Annual Percentage Yield Calculation: https://www.consumerfinance.gov/rules-policy/regulations/1030/2011-12-30/a/
- Consumer Financial Protection Bureau — What is the difference between a loan interest rate and the APR?: https://www.consumerfinance.gov/ask-cfpb/what-is-the-difference-between-a-loan-interest-rate-and-the-apr-en-733/
- Consumer Financial Protection Bureau — Regulation Z, Determination of Annual Percentage Rate: https://www.consumerfinance.gov/rules-policy/regulations/1026/22/

_Prepared for FinQuest seed collection version 1 on 2026-07-26. A human source review is required before learner-facing approval._
