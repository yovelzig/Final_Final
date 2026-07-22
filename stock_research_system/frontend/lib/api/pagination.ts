/** Matches the backend's offset-pagination envelope
 * (`api/pagination.py`): `{"items": [...], "pagination": {"limit",
 * "offset", "returned", "total"}}`. */
export interface PaginatedEnvelope<T> {
  items: T[];
  pagination: {
    limit: number;
    offset: number;
    returned: number;
    total: number;
  };
}

export const DEFAULT_PAGE_LIMIT = 20;
export const MAX_PAGE_LIMIT = 100;

export function hasNextPage(envelope: PaginatedEnvelope<unknown>): boolean {
  return envelope.pagination.offset + envelope.pagination.returned < envelope.pagination.total;
}

export function nextPageOffset(envelope: PaginatedEnvelope<unknown>): number {
  return envelope.pagination.offset + envelope.pagination.returned;
}

/** Clamps a caller-supplied page size into the backend's accepted
 * range, so a UI control can never accidentally request an out-of-range
 * `limit` that the backend would reject with a 422. */
export function clampPageLimit(limit: number): number {
  if (!Number.isFinite(limit)) return DEFAULT_PAGE_LIMIT;
  return Math.min(MAX_PAGE_LIMIT, Math.max(1, Math.trunc(limit)));
}
