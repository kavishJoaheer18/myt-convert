/**
 * The browser only ever talks to this app's own origin: `/api/*` is proxied to
 * the FastAPI container server-side.
 *
 * That buys three things in production. There is no cross-origin request, so no
 * CORS to configure. The API's address is never baked into the *client* bundle,
 * so the page works on any domain. And only one port needs exposing to the
 * internet, which is what a tunnel or a reverse proxy wants.
 *
 * Note that Next resolves this destination when the app is built and stores it
 * in the routes manifest — it is not read again per request. The Docker build
 * therefore sets API_ORIGIN to the compose service name; the default below is
 * for `next dev`, where the API runs on the host.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emits a self-contained server bundle so the Docker image stays small.
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}/:path*`,
      },
    ];
  },
};

export default nextConfig;
