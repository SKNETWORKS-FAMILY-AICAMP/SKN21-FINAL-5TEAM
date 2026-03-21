import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Header from './header/header';
import { AuthProvider } from './authcontext';
import ChatbotFabWrapper from "./ChatbotFabWrapper";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Moyeo Shop",
  description: "Ecommerce Platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <AuthProvider>
          <Header />        
          {children}
          <ChatbotFabWrapper />
        </AuthProvider>
      </body>
    </html>
  );
}
