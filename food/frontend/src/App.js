import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import Header from "./components/Header";
import Chatbot from "./components/chatbot";
import ProductsPage from "./pages/Products";
import LoginPage from "./pages/Login";
import MyPage from "./pages/MyPage";
import Orders from "./pages/Orders";
import layout from "./styles/layout.module.css";
import { AuthProvider } from "./context/AuthContext";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Header />
        <main className={layout.main}>
          <Routes>
            <Route path="/" element={<ProductsPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/mypage" element={<MyPage />} />
            <Route path="/orders" element={<Orders />} />
          </Routes>
        </main>
        <Chatbot />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
