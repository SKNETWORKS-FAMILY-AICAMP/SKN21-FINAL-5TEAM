export class AdapterError extends Error {
  constructor(
    public code:
      | "UNAUTHORIZED"
      | "FORBIDDEN"
      | "NOT_FOUND"
      | "INVALID_INPUT"
      | "NOT_SUPPORTED"
      | "UPSTREAM_ERROR"
      | "UNKNOWN",
    message: string,
    public details?: Record<string, unknown>
  ) {
    super(message);
    this.name = "AdapterError";
  }
}
