// AutonoMath SDK errors.
//
// Hierarchy:
//   AutonoMathError
//     ├─ AuthError       (401 / 403)
//     ├─ NotFoundError   (404)
//     ├─ RateLimitError  (429, with retryAfter)
//     ├─ CapReachedError (402 / monthly ¥-cap reached)
//     ├─ BadRequestError (400 / 422)
//     └─ ServerError     (5xx)
//
// All errors inherit `statusCode` and `body`.

export interface AutonoMathErrorOptions {
  statusCode?: number;
  body?: string;
  cause?: unknown;
}

export class AutonoMathError extends Error {
  public readonly statusCode: number | undefined;
  public readonly body: string | undefined;

  constructor(message: string, options: AutonoMathErrorOptions = {}) {
    super(message);
    this.name = "AutonoMathError";
    this.statusCode = options.statusCode;
    this.body = options.body;
    if (options.cause !== undefined) {
      (this as unknown as { cause: unknown }).cause = options.cause;
    }
  }
}

export class AuthError extends AutonoMathError {
  constructor(message: string, options: AutonoMathErrorOptions = {}) {
    super(message, options);
    this.name = "AuthError";
  }
}

export class NotFoundError extends AutonoMathError {
  constructor(message: string, options: AutonoMathErrorOptions = {}) {
    super(message, options);
    this.name = "NotFoundError";
  }
}

export class BadRequestError extends AutonoMathError {
  constructor(message: string, options: AutonoMathErrorOptions = {}) {
    super(message, options);
    this.name = "BadRequestError";
  }
}

export class RateLimitError extends AutonoMathError {
  public readonly retryAfter: number | undefined;

  constructor(
    message: string,
    options: AutonoMathErrorOptions & { retryAfter?: number } = {},
  ) {
    super(message, { statusCode: options.statusCode ?? 429, body: options.body });
    this.name = "RateLimitError";
    this.retryAfter = options.retryAfter;
  }
}

/**
 * Raised when the user-configured monthly ¥-cap (`POST /v1/me/cap`) is reached.
 * The server returns HTTP 402 with a JSON body containing `cap_reached: true`.
 */
export class CapReachedError extends AutonoMathError {
  public readonly capJpy: number | undefined;
  public readonly currentMonthChargesJpy: number | undefined;

  constructor(
    message: string,
    options: AutonoMathErrorOptions & {
      capJpy?: number;
      currentMonthChargesJpy?: number;
    } = {},
  ) {
    super(message, { statusCode: options.statusCode ?? 402, body: options.body });
    this.name = "CapReachedError";
    this.capJpy = options.capJpy;
    this.currentMonthChargesJpy = options.currentMonthChargesJpy;
  }
}

export class ServerError extends AutonoMathError {
  constructor(message: string, options: AutonoMathErrorOptions = {}) {
    super(message, options);
    this.name = "ServerError";
  }
}
