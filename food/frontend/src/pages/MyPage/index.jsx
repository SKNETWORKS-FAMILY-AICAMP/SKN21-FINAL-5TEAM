import React from "react";
import layout from "../../styles/layout.module.css";

const MyPage = () => (
  <div className={layout.section}>
    <div style={styles.container}>
      <h1 style={styles.title}>마이페이지</h1>
      <p style={styles.subtitle}>
        주문 내역, 배송지, 이벤트 혜택을 한 곳에서 확인할 수 있습니다.
      </p>
      <div style={styles.card}>
        <p style={styles.cardLabel}>최근 주문</p>
        <p style={styles.cardValue}>아직 주문 내역이 없습니다.</p>
      </div>
      <div style={styles.card}>
        <p style={styles.cardLabel}>포인트</p>
        <p style={styles.cardValue}>0 포인트</p>
      </div>
    </div>
  </div>
);

const styles = {
  container: {
    minHeight: "calc(100vh - 64px)",
    padding: "3rem 1rem",
    display: "flex",
    flexDirection: "column",
    gap: "1.5rem",
    alignItems: "center",
    justifyContent: "flex-start",
    fontFamily: "Pretendard, sans-serif",
  },
  title: {
    margin: 0,
    fontSize: "2rem",
    fontWeight: 700,
  },
  subtitle: {
    margin: 0,
    fontSize: "1rem",
    color: "#556b2f",
    textAlign: "center",
    maxWidth: "480px",
  },
  card: {
    width: "100%",
    maxWidth: "520px",
    padding: "1.25rem 1.5rem",
    borderRadius: "18px",
    border: "1px solid #dfe6e0",
    backgroundColor: "#fff",
    boxShadow: "0 20px 40px rgba(0, 0, 0, 0.05)",
  },
  cardLabel: {
    margin: 0,
    color: "#7a7a7a",
    fontSize: "0.85rem",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  cardValue: {
    margin: "0.5rem 0 0",
    fontSize: "1.2rem",
    fontWeight: 600,
  },
};

export default MyPage;
