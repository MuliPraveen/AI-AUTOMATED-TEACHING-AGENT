/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  // Browser calls same-origin /api and /ws; Next proxies to FastAPI.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/media/:path*", destination: `${backend}/api/media/:path*` },
    ];
  },
};
