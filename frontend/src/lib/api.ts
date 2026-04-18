export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}
