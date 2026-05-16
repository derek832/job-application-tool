const STORAGE_KEY = "jat_api_token";

export function saveToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
}

export function loadToken(): string | null {
  return localStorage.getItem(STORAGE_KEY) || null;
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
}
