import React, { useState } from "react";
import layout from "../../styles/layout.module.css";

const Login = () => {
  const [form, setForm] = useState({ email: "", password: "" });
  const handleChange = (event) => {
    setForm({ ...form, [event.target.name]: event.target.value });
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    alert(`Submitting ${form.email}`);
  };

  return (
    <div className={layout.section}>
      <div style={styles.page}>
        <form style={styles.card} onSubmit={handleSubmit}>
          <h1 style={styles.title}>로그인</h1>
          <p style={styles.subtitle}>Yaam에 오신 것을 환영합니다.</p>
          <label style={styles.label}>
            이메일
            <input
              type="email"
              name="email"
              value={form.email}
              onChange={handleChange}
              style={styles.input}
              placeholder="아이디를 입력해주세요"
              required
            />
          </label>
          <label style={styles.label}>
            비밀번호
            <input
              type="password"
              name="password"
              value={form.password}
              onChange={handleChange}
              style={styles.input}
              placeholder="비밀번호를 입력해주세요"
              required
            />
          </label>
          <button type="submit" style={styles.primaryButton}>
            로그인
          </button>
          <button type="button" style={styles.secondaryButton}>
            회원가입
          </button>
        </form>
      </div>
    </div>
  );
};

const styles = {
  page: {
    minHeight: "calc(100vh - 64px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
    fontFamily: "Pretendard, sans-serif",
    padding: "3rem 0",
    color: "#111",
  },
  card: {
    width: "100%",
    maxWidth: "420px",
    backgroundColor: "#fff",
    borderRadius: "24px",
    padding: "3rem 2.5rem",
    boxShadow: "0 20px 40px rgba(0, 0, 0, 0.08)",
    textAlign: "center",
  },
  title: {
    margin: 0,
    marginBottom: "0.25rem",
    fontSize: "2rem",
    color: "#0d330e",
  },
  subtitle: {
    margin: "0 0 1.5rem",
    fontSize: "0.95rem",
    color: "#183f0e",
  },
  label: {
    display: "block",
    textAlign: "left",
    fontSize: "0.85rem",
    color: "#111",
    marginBottom: "0.35rem",
  },
  input: {
    width: "100%",
    padding: "0.9rem 1rem",
    marginTop: "0.25rem",
    borderRadius: "12px",
    border: "1px solid #c8e6c9",
    fontSize: "1rem",
    color: "#1b1b1b",
    boxSizing: "border-box",
  },
  primaryButton: {
    width: "100%",
    padding: "0.9rem",
    marginTop: "1.4rem",
    borderRadius: "16px",
    border: "none",
    backgroundColor: "#2e7d32",
    color: "#fff",
    fontSize: "1rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  secondaryButton: {
    width: "100%",
    padding: "0.9rem",
    marginTop: "0.75rem",
    borderRadius: "16px",
    border: "1.5px solid #2e7d32",
    backgroundColor: "transparent",
    color: "#2e7d32",
    fontSize: "1rem",
    fontWeight: 600,
    cursor: "pointer",
  },
};

export default Login;
