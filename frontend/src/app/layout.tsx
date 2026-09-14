import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Uganda Health Performance Intelligence",
  description: "Permission-safe MNCH performance dashboards for authorised users.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-canvas text-navy antialiased">{children}</body>
    </html>
  );
}
