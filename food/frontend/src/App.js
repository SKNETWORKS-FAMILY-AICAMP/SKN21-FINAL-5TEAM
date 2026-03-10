import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import Header from "./components/Header";
import ProductsPage from "./pages/Products";
import LoginPage from "./pages/Login";
import MyPage from "./pages/MyPage";
import layout from "./styles/layout.module.css";

function App() {
  return (
    <BrowserRouter>
      <Header />
      <main className={layout.main}>
        <Routes>
          <Route path="/" element={<ProductsPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/mypage" element={<MyPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

export default App;
