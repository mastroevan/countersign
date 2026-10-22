import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Countersign — Doorbell Delivery Verification",
  description:
    "Independent second witness checking carrier delivered scans against Ring doorbell cameras. Amazon Developer Hackathon project.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-amber-500/30 selection:text-amber-200">
        {children}
      </body>
    </html>
  );
}
