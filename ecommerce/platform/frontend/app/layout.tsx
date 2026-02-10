import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Header from './header/header';
import ChatbotFab from "./chatbot/chatbotfab";

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
        <Header />        
        {children}
        <ChatbotFab />
      </body>
    </html>
  );
}


