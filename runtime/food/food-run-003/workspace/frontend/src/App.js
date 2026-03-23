import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import Header from "./components/Header";
import ProductsPage from "./pages/Products";
import LoginPage from "./pages/Login";
import Orders from "./pages/Orders";
import layout from "./styles/layout.module.css";
import { AuthProvider } from "./context/AuthContext";

import SharedChatbotWidget from "./chatbot/SharedChatbotWidget";
function App() {
  return (
    <AuthProvider>      <BrowserRouter>
        <Header />
        <main className={layout.main}>
          <Routes>
            <Route path="/" element={<ProductsPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/orders" element={<Orders />} />
      <SharedChatbotWidget />
          </Routes>
        </main>
      </BrowserRouter>    </AuthProvider>
  );
}

export default App;
