import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Per-request nonce + CSP.
 *
 * Next.js 14 ships three flavours of inline ``<script>`` in its
 * server-rendered HTML: the RSC streaming bootstrap
 * (``self.__next_f.push``), the framework hydration glue, and the
 * pre-hydration theme setter we render via `next-themes`. A static
 * ``script-src 'self'`` breaks all three; ``'unsafe-inline'`` accepts
 * them but also accepts every XSS payload. The right answer is a
 * per-request nonce — Next.js reads ``x-nonce`` off the request headers
 * and stamps the value on every inline script it emits, so the browser
 * only runs scripts that carry the matching ``nonce`` attribute. We
 * use ``'strict-dynamic'`` so scripts loaded by those nonced bootstrap
 * scripts (the chunk files) don't need their own nonce.
 *
 * Skipped paths: static assets and API routes. Static assets have no
 * HTML and so no ``<script>`` the CSP would affect; API routes are
 * JSON/redirect responses that don't render as documents.
 */
export function middleware(request: NextRequest) {
  const nonce = generateNonce();
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export const config = {
  matcher: [
    // Every route except: API, Next internals, favicon, and any file
    // with an extension (so static assets pass through). Prefetches
    // are also skipped so Next's router prefetch requests don't each
    // burn a nonce-rotation — they reuse the page's CSP behaviour.
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
