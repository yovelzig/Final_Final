import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Produces a minimal, self-contained server bundle (only the
  // node_modules actually reachable from the build are traced in) -
  // what the Docker runtime stage copies, instead of the full
  // node_modules tree.
  output: "standalone",
};

export default nextConfig;
