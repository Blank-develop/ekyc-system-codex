// Small client-side JWT holder. The token is kept in localStorage so an operator
// stays logged in across reloads, and mirrored in memory for synchronous reads by
// the API layer. This is for the staff/admin console only — the public
// verification flow does not require a login.

const STORAGE_KEY = "kyron.auth.token";

let currentToken: string | null =
  typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;

export const getAuthToken = (): string | null => currentToken;

export const setAuthToken = (token: string | null): void => {
  currentToken = token;
  if (typeof window === "undefined") return;
  if (token) {
    window.localStorage.setItem(STORAGE_KEY, token);
  } else {
    window.localStorage.removeItem(STORAGE_KEY);
  }
};

export const clearAuthToken = (): void => setAuthToken(null);
