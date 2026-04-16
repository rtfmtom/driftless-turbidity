import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Driftless Clarity",
  description: "Stream turbidity and water clarity monitoring for the Driftless Area.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#f8fafc",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto max-w-6xl px-3 py-4 sm:px-4 sm:py-6">
          {children}
        </div>
      </body>
    </html>
  );
}
