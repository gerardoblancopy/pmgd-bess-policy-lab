import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root: a stray lockfile exists in the user home directory
  turbopack: { root: path.join(__dirname) },
};

export default nextConfig;
