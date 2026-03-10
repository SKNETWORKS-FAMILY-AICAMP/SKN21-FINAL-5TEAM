import React from "react";
import { Link } from "react-router-dom";

const Header = () => (
  <header style={styles.header}>
    <div style={styles.left}>
      <button type="button" style={styles.menuButton}>
        ☰
      </button>
      <div style={styles.brand}>
        <Link to="/" style={styles.logo}>
          Yaam
        </Link>
      </div>
    </div>
    <div style={styles.searchWrapper}>
      <input
        type="text"
        placeholder="상품명을 검색하세요"
        style={styles.searchInput}
      />
    </div>
    <nav style={styles.right}>
      <Link to="/orders" style={styles.link}>
        상품목록
      </Link>
      <Link to="/mypage" style={styles.link}>
        마이
      </Link>
      <Link to="/login" style={styles.link}>
        로그인
      </Link>
    </nav>
  </header>
);

const styles = {
  header: {
    position: "sticky",
    top: 0,
    zIndex: 100,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    height: "64px",
    padding: "0 2rem",
    backgroundColor: "#fff",
    borderBottom: "1px solid #eaeaea",
    boxShadow: "0 2px 10px rgba(0, 0, 0, 0.08)",
  },
  left: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
  },
  menuButton: {
    fontSize: "24px",
    background: "none",
    border: "none",
    cursor: "pointer",
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
  },
  logo: {
    fontSize: "1.15rem",
    fontWeight: 600,
    color: "#111",
    textDecoration: "none",
  },
  divider: {
    color: "#ccc",
  },
  searchWrapper: {
    flex: 1,
    display: "flex",
    justifyContent: "center",
  },
  searchInput: {
    width: "420px",
    maxWidth: "100%",
    height: "40px",
    borderRadius: "20px",
    border: "1px solid #d9d9d9",
    padding: "0 1rem",
    outline: "none",
  },
  right: {
    display: "flex",
    alignItems: "center",
    gap: "1rem",
  },
  link: {
    color: "#111",
    textDecoration: "none",
    fontWeight: 500,
  },
};

export default Header;
