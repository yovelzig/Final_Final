---
document_id: "kb-en-013"
title: "Technical Analysis Foundations"
slug: "technical-analysis-foundations"
version: 1
language: "en"
difficulty:
  - "intermediate"
content_type: "educational_reference"
jurisdiction: "general"
review_status: "approved_seed"
collection: "finquest_core_financial_education"
concept_ids:
  - "price_chart"
  - "candlestick"
  - "timeframe"
  - "trend"
  - "support_resistance"
  - "moving_average"
  - "momentum"
  - "volume"
  - "relative_strength_index"
  - "moving_average_convergence_divergence"
  - "breakout"
  - "false_breakout"
  - "backtest"
  - "overfitting"
  - "transaction_cost"
lesson_ids: []
source_policy: "authoritative_and_educational"
created_at: "2026-07-26"
reviewed_at: "2026-07-26"
requires_periodic_review: true
---

# Technical Analysis Foundations

> **Educational scope:** This document presents technical analysis as a framework for describing and testing market behavior. It does not provide personalized investment advice, recommend a security, or claim that an indicator can predict future prices with certainty.

## Learning Objectives

After studying this document, a learner should be able to:

- Read line, bar, and candlestick charts without treating visual patterns as facts about the future.
- Explain how timeframe selection changes the meaning of trends, support, resistance, momentum, and volume.
- Calculate a simple moving average and describe the logic of RSI and MACD.
- Define breakouts and false breakouts using explicit rules rather than hindsight.
- Identify confirmation bias, look-ahead bias, data snooping, overfitting, and omitted transaction costs.
- Convert a chart idea into a testable hypothesis with entry, exit, timing, cost, and risk assumptions.

## Prerequisite Knowledge

The learner should understand open, high, low, and closing prices; percentage returns; averages; trading volume; order execution; bid-ask spreads; and the difference between historical evidence and a forecast. Familiarity with drawdown and risk management is helpful.

## Core Concepts

### Price charts and candlesticks

A **price chart** places market data on a time axis. A line chart commonly connects closing prices. A bar or candlestick chart displays the open, high, low, and close for each period. A candlestick body represents the distance between the open and close, while the upper and lower shadows represent prices traded above and below the body.

Candlestick color conventions vary by platform. The data values matter more than the color. One candle summarizes a period; it does not reveal every trade, the sequence of trades inside the period, or the motives of buyers and sellers.

### Timeframes

A **timeframe** defines how much activity each chart bar represents, such as five minutes, one day, or one week. The same market may appear to be rising on a weekly chart, falling on a daily chart, and moving sideways on an hourly chart. These statements can all be true because they describe different horizons.

A rule must therefore name its timeframe. “The trend is up” is incomplete. “The daily closing price has remained above a rising 50-day moving average for 15 sessions” is more testable.

### Trend, support, and resistance

A **trend** is a directional pattern defined over a chosen horizon. A common visual description of an uptrend is a sequence of higher highs and higher lows; a downtrend may show lower highs and lower lows. A precise system should define how highs and lows are identified.

**Support** is an area where falling prices have previously slowed, paused, or reversed. **Resistance** is an area where rising prices have previously slowed, paused, or reversed. These are zones inferred from observations, not physical barriers. A level can fail, and analysts may draw different zones from the same chart.

### Moving averages

A **simple moving average**, or SMA, is the arithmetic mean of the most recent prices in a rolling window:

`SMA(n) = (P1 + P2 + ... + Pn) / n`

Here, `n` is the number of periods and each `P` is the selected price, commonly the closing price. A 20-day SMA uses 20 daily observations and is measured in the same currency units as price. Moving averages smooth short-term variation but lag because they use past data.

An **exponential moving average**, or EMA, gives greater weight to recent observations. Different windows and weighting methods can produce different signals. A crossover does not prove that a new trend will persist.

### Momentum and volume

**Momentum** describes the rate or persistence of price change. A basic momentum measure is the percentage return over a selected lookback period:

`Momentum return = (current price / past price) - 1`

The result is usually expressed as a percentage. Momentum depends on the lookback horizon and can reverse sharply.

**Volume** is the number of shares, contracts, or units traded during a period. Analysts use volume as context for participation and liquidity. High volume does not reveal whether future prices will rise or fall, and volume data may differ across venues or instruments.

### RSI and MACD

The **Relative Strength Index**, or RSI, is an oscillator that compares the size of recent upward moves with recent downward moves. It is commonly displayed from 0 to 100. Thresholds such as 70 and 30 are conventions, not natural laws. A high RSI can remain high during a strong trend, and a low RSI can remain low during a persistent decline.

The **Moving Average Convergence Divergence**, or MACD, is based on the difference between two exponential moving averages. A commonly used version subtracts a 26-period EMA from a 12-period EMA and compares that result with a 9-period EMA called the signal line. These settings are conventions and may not suit every market or timeframe. MACD is derived from price, so it can lag and cannot independently confirm a causal explanation.

### Breakouts and false breakouts

A **breakout** occurs when price moves beyond a predefined support, resistance, range, or pattern boundary. A rule should state whether the trigger uses an intraday trade, a closing price, a percentage buffer, volume, or a waiting period.

A **false breakout** is a move beyond the boundary that does not persist under the rule's confirmation criteria. Calling a move false only after seeing the later reversal creates hindsight. The definition must be written before the test.

## Detailed Explanation

### Technical analysis is descriptive before it is predictive

Charts organize market-generated data. Indicators transform those data using formulas. They may help describe direction, speed, variability, participation, or proximity to a previously observed level. They do not create new fundamental information and do not establish why a price moved.

Two indicators may appear to confirm each other while using nearly identical inputs. For example, a moving-average crossover and MACD both depend on transformations of past prices. Their agreement may reflect redundancy rather than independent evidence.

A disciplined interpretation separates three statements:

1. **Observation:** the daily close is above the 50-day SMA.
2. **Rule:** a strategy classifies this condition as positive trend evidence.
3. **Forecast:** the analyst expects a higher future return.

The observation is directly measurable. The rule is a chosen convention. The forecast is uncertain and must be tested.

### Timeframe alignment and signal timing

A signal calculated from a closing price is not known until that close occurs. A backtest must not assume execution at the same closing price unless the order could realistically have been submitted and filled with that information. A safer educational assumption is that a closing signal becomes actionable at the next available trading opportunity, with a stated execution-price rule.

Indicators must also use data available at the decision time. Revised data, future constituents, later corporate-action adjustments, or a range that uses tomorrow's high introduce information leakage. This is often called **look-ahead bias**.

### Chart patterns and subjectivity

Patterns such as triangles, channels, head-and-shoulders formations, or candlestick combinations can be useful vocabulary. Their classification can also be subjective. Different analysts may choose different start points, trend lines, tolerances, and confirmation rules.

To study a pattern, convert it into measurable conditions. Specify the required number of observations, maximum deviation from a line, breakout threshold, holding period, exit rule, and invalidation rule. If the definition changes after inspecting results, the analysis has become partly in-sample.

### Confirmation bias in chart reading

**Confirmation bias** is the tendency to emphasize information that supports an existing view and discount conflicting evidence. A bullish analyst may draw support from the most favorable lows, ignore a weak volume reading, or change timeframes until a desired pattern appears.

Controls include writing the rule before opening the chart, using the same procedure for favorable and unfavorable cases, recording invalidation conditions, and asking another reviewer to classify the same observations independently.

### Backtesting, overfitting, and multiple testing

A **backtest** applies a fully specified rule to historical data as though decisions were made sequentially. A useful test preserves chronology and records signals, executions, costs, positions, returns, and drawdowns.

**Overfitting** occurs when a rule captures noise or unique features of the development sample rather than a durable relationship. Testing many indicators, windows, thresholds, markets, and exits increases the chance of finding an attractive result by luck. Selecting the best result and reporting it as though it were the only test understates uncertainty.

A stronger process separates development data from out-of-sample data, limits parameter choices, reports all material tests, uses walk-forward evaluation where appropriate, checks sensitivity to nearby settings, and compares results across market regimes. Out-of-sample success still does not guarantee future performance.

### Transaction costs and implementation

Gross backtest returns are not the same as realizable net returns. A strategy may incur commissions, fees, bid-ask spreads, slippage, market impact, financing costs, taxes, and delays. Costs generally increase with turnover and can vary with market liquidity and order size.

A test should state costs per trade or use a documented model. It should also show results under less favorable cost assumptions. A small gross advantage that disappears after reasonable costs is not a robust result.

## Worked Examples

### Hypothetical example 1: simple moving average

Assume a hypothetical asset has five daily closing prices of $98, $100, $101, $99, and $102.

`5-day SMA = ($98 + $100 + $101 + $99 + $102) / 5 = $100`

The latest close of $102 is $2, or 2%, above the SMA. This describes the relationship between current price and its recent average. It does not prove that the next close will be higher.

### Hypothetical example 2: breakout rule

Assume resistance is defined before the test as the highest daily close during the previous 20 sessions. A breakout signal requires the current daily close to exceed that level by at least 1%. Execution is assumed at the next day's opening price. The position is closed after 10 sessions or after a 4% decline from the entry price, whichever occurs first.

This rule is imperfect, but it is testable. “Buy when the chart looks ready to break out” is not reproducible enough for a meaningful backtest.

### Hypothetical example 3: costs change the conclusion

A hypothetical strategy makes 40 round trips during a year. Before costs, it earns 6.0%. Assume total spread, fees, and slippage average 0.12% per round trip.

`Estimated trading cost = 40 × 0.12% = 4.8%`

`Estimated net return before taxes = 6.0% - 4.8% = 1.2%`

The example shows why turnover and costs must be included. Actual costs can differ from assumptions.

## Common Mistakes

- Treating a chart label as a causal explanation for a price move.
- Changing timeframes or trend lines until the preferred conclusion appears.
- Calling support and resistance exact prices rather than uncertain zones.
- Interpreting RSI above 70 as an automatic sell signal or RSI below 30 as an automatic buy signal.
- Combining several price-derived indicators and assuming they provide independent confirmation.
- Using today's close to create a signal and also assuming execution at that same close.
- Testing many parameter combinations but reporting only the best one.
- Ignoring delisted assets, changing index membership, spreads, slippage, fees, and taxes.
- Assuming a visually attractive historical pattern must continue.

## Common Misconceptions

**“A candlestick pattern predicts the next move.”** A candlestick summarizes historical prices for a period. Any predictive claim requires a precise definition and evidence from an appropriately designed test.

**“More indicators make a signal safer.”** Additional indicators may repeat the same price information and can create more opportunities to overfit.

**“A profitable backtest proves a strategy works.”** A backtest can be affected by luck, information leakage, survivorship bias, parameter selection, omitted costs, and market changes.

**“A breakout that reverses was obviously false.”** It is obvious only after later prices are known. A valid rule defines confirmation and failure in advance.

**“Technical analysis is either perfect prediction or completely useless.”** This is a false choice. Technical tools can organize data, define risk rules, support execution planning, or generate hypotheses without guaranteeing an advantage.

## Practical Application

Use this checklist before relying on a technical rule:

1. Name the instrument, data source, timeframe, and adjustment method.
2. Define every indicator formula, parameter, and threshold.
3. State when the signal becomes known and when execution can occur.
4. Define entry, exit, position, and invalidation rules before testing.
5. Separate development, validation, and final evaluation periods.
6. Include inactive or delisted instruments where relevant and avoid future constituent information.
7. Estimate spreads, fees, slippage, market impact, financing, and taxes where applicable.
8. Compare with a simple benchmark and report turnover and drawdown.
9. Test nearby parameter values and unfavorable subperiods.
10. Record failed rules as well as successful ones.
11. Describe the result as historical evidence, not a certainty.

A learner can practice by selecting one simple indicator, writing a one-page rule specification, and asking whether another person could reproduce every signal without additional judgment.

## Knowledge Check

1. What information does a candlestick contain, and what information does it omit?
2. Why can the same market have different trends on different timeframes?
3. Calculate the three-period SMA for closing prices of $30, $33, and $36.
4. Why is a moving average described as a lagging measure?
5. What is the difference between a breakout observation and a forecast?
6. Why do RSI thresholds such as 70 and 30 require context?
7. What is look-ahead bias in a backtest?
8. How can testing many parameter combinations create overfitting?
9. Why must transaction costs be included in a technical-strategy test?
10. Name two controls that reduce confirmation bias in chart analysis.

## Knowledge Check Answers

1. A candlestick contains the open, high, low, and close for a period. It omits the complete sequence of trades, order-book conditions, participant motives, and events outside the selected interval.
2. Each timeframe aggregates a different horizon. Short-term declines can occur inside a long-term rise, so trend statements must name their timeframe and rule.
3. `($30 + $33 + $36) / 3 = $33`. The SMA is $33.
4. It is calculated from past observations. Smoothing reduces short-term noise but delays the response to new price changes.
5. A breakout observation states that price crossed a predefined boundary. A forecast claims something about future behavior and remains uncertain.
6. The thresholds are conventions. Strong trends can keep RSI elevated or depressed, and results depend on the market, period, and rule.
7. Look-ahead bias occurs when a test uses information that was not available at the simulated decision time, such as future prices or later index constituents.
8. With enough alternatives, some combinations can look successful by chance. Choosing the best historical result may fit noise rather than a durable relationship.
9. Trading costs reduce returns and often rise with turnover. A rule that appears profitable before costs may be unprofitable after realistic implementation assumptions.
10. Examples include defining rules before viewing outcomes, recording invalidation criteria, using consistent chart procedures, and obtaining independent classification from another reviewer.

## Key Takeaways

- Technical analysis transforms historical price and volume data; it does not create certainty.
- Chart interpretation depends on timeframe, definitions, data quality, and signal timing.
- Support, resistance, momentum, RSI, MACD, and breakouts are frameworks with limitations, not guarantees.
- Reproducible rules are more testable than flexible visual narratives.
- Backtests require chronological data, realistic execution, out-of-sample evaluation, and full cost assumptions.
- Overfitting and confirmation bias can make weak ideas appear persuasive.
- The responsible conclusion is conditional: a rule may have shown historical behavior under stated assumptions, but future outcomes can differ.

## Glossary

- **Backtest:** Historical simulation of a fully specified decision rule.
- **Breakout:** Price movement beyond a predefined boundary.
- **Candlestick:** Chart element showing open, high, low, and close for one period.
- **Confirmation bias:** Preference for evidence that supports an existing belief.
- **EMA:** Exponential moving average that gives greater weight to recent data.
- **False breakout:** Boundary crossing that fails under criteria defined before evaluation.
- **Look-ahead bias:** Use of information unavailable at the historical decision time.
- **MACD:** Momentum indicator based on the difference between exponential moving averages.
- **Momentum:** Direction or rate of price change over a selected horizon.
- **Overfitting:** Fitting a rule to historical noise or sample-specific features.
- **Resistance:** Area where rising price has previously slowed or reversed.
- **RSI:** Oscillator comparing recent upward and downward price moves.
- **SMA:** Arithmetic mean of prices over a rolling number of periods.
- **Support:** Area where falling price has previously slowed or reversed.
- **Transaction cost:** Cost of implementing trades, including fees, spread, slippage, and market impact.
- **Volume:** Number of shares, contracts, or units traded during a period.

## References and Further Reading

- CME Group, “Technical Analysis.” https://www.cmegroup.com/education/courses/trading-and-analysis/technical-analysis
- CME Group, “Chart Types: Candlestick, Line, Bar.” https://www.cmegroup.com/education/courses/technical-analysis/chart-types-candlestick-line-bar
- CME Group, “Support and Resistance.” https://www.cmegroup.com/education/courses/trading-and-analysis/support-and-resistance.hideSubnav.educationIframe.html?hideAddThisExt=y&hideFooter=y&hideHeader=y&hideRightRail=y
- CME Group, “Understanding Moving Averages.” https://www.cmegroup.com/education/courses/technical-analysis/understanding-moving-averages
- CME Group, “Oscillators: MACD, RSI, Stochastics.” https://www.cmegroup.com/education/courses/technical-analysis/oscillators-macd-rsi-stochastics
- Bailey, David H.; Borwein, Jonathan M.; López de Prado, Marcos; and Zhu, Qiji Jim, “The Probability of Backtest Overfitting.” https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- U.S. Securities and Exchange Commission staff, “Standards of Conduct for Broker-Dealers and Investment Advisers Care Obligations.” https://www.sec.gov/about/divisions-offices/division-trading-markets/broker-dealers/staff-bulletin-standards-conduct-broker-dealers-investment-advisers-care-obligations
- U.S. Securities and Exchange Commission and Library of Congress, “Behavioral Patterns of U.S. Investors.” https://www.sec.gov/investor/tools/behaviorialpatterns.htm
