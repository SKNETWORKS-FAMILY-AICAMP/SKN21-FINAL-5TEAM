/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    externalDir: true,
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
    NEXT_PUBLIC_CHATBOT_API_URL: process.env.NEXT_PUBLIC_CHATBOT_API_URL || "http://localhost:8100",
  },
  transpilePackages: ['@skn/shared-chatbot'],
};

module.exports = nextConfig;
