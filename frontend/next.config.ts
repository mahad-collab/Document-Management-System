import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next's dev server only trusts requests whose Origin/Host is localhost
  // by default (a DNS-rebinding protection) — without this, opening the
  // app from a LAN IP loads the initial HTML fine but the dev-server's own
  // HMR websocket (and some internal RSC requests) get rejected, which is
  // exactly the "WebSocket handshake failed" error this was added for.
  // "desktop-3e2t2nd.local" resolves via mDNS to this machine's current
  // address on whatever network it's on — added once here, it keeps
  // working across every future network change without editing this list
  // again. The raw IPs below are kept only for networks where mDNS
  // resolution might not work (e.g. client-isolated guest Wi-Fi).
  allowedDevOrigins: [
    "desktop-3e2t2nd.local",
    "10.58.1.64",
    "192.168.11.1",
    "192.168.18.178",
    "192.168.0.107",
    "10.58.1.242",
    "localhost",
    "127.0.0.1",
  ],
  // Next only allows one dev server per build directory (a lock file
  // enforces it) — running a second instance (the HTTPS one on :3443, for
  // LAN access) needs its own distDir so it doesn't collide with the
  // normal http://localhost:3000 instance. Launch it with
  // NEXT_DIST_DIR=.next-https set; the default instance is unaffected.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
