"use client";

import { useRouter } from "next/navigation";
import styles from "./mypage.module.css";

export default function MyPage() {
  const router = useRouter();

  const handleLogout = () => {
    router.push("/auth/login");
  };

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        {/* ===== AppBar ===== */}
        <header className={styles.appBar}>
          <h2 className={styles.appBarTitle}>마이</h2>
          <div className={styles.appBarActions}>
            <button aria-label="알림">🔔</button>
            <button aria-label="설정">⚙️</button>
          </div>
        </header>

        {/* ===== Profile ===== */}
        <section className={styles.profileCard}>
          {/* 🔽 [추가] 프로필 클릭 시 profile 페이지 이동 */}
          <div
            className={styles.profileLeft}
            onClick={() => router.push("/mypage/profile")}
            style={{ cursor: "pointer" }}
          >
            <div className={styles.profileImage}>
              <img
                src="https://image.msscdn.net/mfile_s01/_simbols/_basic/basic.png"
                alt="프로필 이미지"
              />
            </div>

            <div className={styles.profileText}>
              <span className={styles.nickname}>다들 파이팅</span>
              <span className={styles.arrow}>›</span>
            </div>
          </div>

          <button className={styles.snapButton}>스냅 프로필</button>
        </section>

        {/* ===== Shortcut Grid ===== */}
        <section className={styles.shortcutGrid}>
          <button className={styles.shortcutItem}>
            <div className={styles.shortcutTitle}>
              <span>포인트</span>
              <span className={styles.arrow}>›</span>
            </div>
            <div className={styles.shortcutValue}>3,000원</div>
          </button>

          <button className={styles.shortcutItem}>
            <div className={styles.shortcutTitle}>
              <span>상품권</span>
              <span className={styles.arrow}>›</span>
            </div>
            <div className={styles.shortcutValue}>충전하기</div>
          </button>

          <button className={styles.shortcutItem}>
            <div className={styles.shortcutTitle}>
              <span>쿠폰</span>
              <span className={styles.arrow}>›</span>
            </div>
            <div className={styles.shortcutValue}>2장</div>
          </button>
        </section>

        {/* ===== Menu List ===== */}
        <section className={styles.menuSection}>
          <ul>
            <li>주문목록</li>
            <li>취소 / 반품 / 교환 내역</li>
            <li>재입고 알림 내역</li>
            <li>최근 본 상품</li>
            <li>유즈드</li>
            <li>나의 맞춤 정보(체형)</li>

            {/* 🔽 [추가] 1:1 문의 내역 → ask 페이지 이동 */}
            <li
              onClick={() => router.push("/mypage/ask")}
              style={{ cursor: "pointer" }}
            >
              1:1 문의 내역
            </li>
          </ul>
        </section>

        {/* ===== Logout ===== */}
        <section className={styles.logoutSection}>
          <button className={styles.logoutButton} onClick={handleLogout}>
            로그아웃
          </button>
        </section>
      </div>
    </div>
  );
}
