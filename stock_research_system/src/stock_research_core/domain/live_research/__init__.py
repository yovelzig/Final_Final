"""Phase G1: provider-neutral Live Research domain.

Models the lifecycle of a research question (`ResearchRequest`), its
execution attempts (`ResearchRun`), the provenance it gathers
(`EvidenceItem`), and the claims derived from that evidence
(`ResearchClaim`, `ClaimEvidenceLink`).

This package has no knowledge of any provider (Perplexity, SEC EDGAR,
yfinance, OpenAI, ...) or infrastructure (databases, queues, HTTP
frameworks) - the same rule every other `domain/*` package follows.
"""
