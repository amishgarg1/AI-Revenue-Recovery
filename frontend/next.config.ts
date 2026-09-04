import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide Next's floating dev-tools badge. It only ever appeared in `next dev`,
  // never in a production build, but the demo is recorded against the dev
  // server and a framework logo in the corner of the screen reads as part of
  // the product. Compile and runtime errors are still surfaced.
  devIndicators: false,
};

export default nextConfig;
