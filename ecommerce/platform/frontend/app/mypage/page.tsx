"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import styles from "./mypage.module.css";

type ModalType =
  | "profile"
  | "password"
  | "style"
  | "alarm"
  | "withdraw"
  | null;

export default function MyPage() {
  const router = useRouter();

  /* =========================
     유저 로드
  ========================= */
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    fetch("http://localhost:8000/users/me", {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) {
          router.replace("/auth/login");
          return;
        }
        const data = await res.json();
        setUser(data);

        setProfileForm({
          name: data.name ?? "",
          phone: data.phone ?? "",
        });

        setAlarmForm({
          agree_marketing: Boolean(data.agree_marketing),
          agree_sms: Boolean(data.agree_sms),
          agree_email: Boolean(data.agree_email),
        });
      })
      .catch(() => router.replace("/auth/login"));
  }, [router]);

  /* =========================
     모달 상태
  ========================= */
  const [openModal, setOpenModal] = useState<ModalType>(null);
  const closeModal = () => setOpenModal(null);

  /* =========================
     회원정보 변경
  ========================= */
  const [profileForm, setProfileForm] = useState({
    name: "",
    phone: "",
  });

  const handleSaveProfile = async () => {
    await fetch("http://localhost:8000/users/me", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profileForm),
    });
    closeModal();
  };

  /* =========================
     비밀번호 변경
  ========================= */
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  });

  const handleSavePassword = async () => {
    if (passwordForm.newPassword !== passwordForm.confirmPassword) return;

    await fetch("http://localhost:8000/users/me/password", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: passwordForm.currentPassword,
        new_password: passwordForm.newPassword,
      }),
    });

    closeModal();
  };

  /* =========================
     알림 설정
  ========================= */
  const [alarmForm, setAlarmForm] = useState({
    agree_marketing: true,
    agree_sms: true,
    agree_email: true,
  });

  const handleSaveAlarm = async () => {
    await fetch("http://localhost:8000/users/me", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(alarmForm),
    });
    closeModal();
  };

  /* =========================
     체형 정보
  ========================= */
  const [form, setForm] = useState<any>({});
  const [openUpper, setOpenUpper] = useState(false);
  const [openLower, setOpenLower] = useState(false);

  const loadBodyMeasurement = async () => {
    const res = await fetch(
      "http://localhost:8000/users/me/body-measurement",
      { credentials: "include" }
    );
    if (!res.ok) return;
    const data = await res.json();
    setForm(data);
  };

  useEffect(() => {
    if (openModal === "style") loadBodyMeasurement();
  }, [openModal]);

  const handleChange = (e: any) => {
    const { name, value } = e.target;
    setForm((prev: any) => ({ ...prev, [name]: value }));
  };

  const handleSaveStyle = async () => {
    await fetch("http://localhost:8000/users/me/body-measurement", {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    closeModal();
  };

  /* =========================
     회원 탈퇴
  ========================= */
  const [withdrawReason, setWithdrawReason] = useState("");

  const handleWithdraw = async () => {
    await fetch("http://localhost:8000/users/me", {
      method: "DELETE",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: withdrawReason }),
    });
    router.replace("/auth/login");
  };

  /* =========================
     로그아웃
  ========================= */
  const handleLogout = async () => {
    await fetch("http://localhost:8000/users/logout", {
      method: "POST",
      credentials: "include",
    });
    router.replace("/auth/login");
  };

  if (!user) return null;

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        {/* ===== AppBar ===== */}
        <header className={styles.appBar}>
          <h2 className={styles.appBarTitle}>마이</h2>
        </header>

        {/* ===== Profile ===== */}
        <section className={styles.profileCard}>
          <div className={styles.profileLeft}>
            <div className={styles.profileImage}>
              <img
                src="https://image.msscdn.net/mfile_s01/_simbols/_basic/basic.png"
                alt="프로필 이미지"
              />
            </div>

            <div className={styles.profileText}>
              <span className={styles.nickname}>{user.name}</span>
            </div>
          </div>

          {/* <button className={styles.snapButton}>스냅 프로필</button> */}
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
            <li
              onClick={() => router.push("/order")}
              style={{ cursor: "pointer" }}
            >
              주문목록
            </li>

            <li>취소 / 반품 / 교환 내역</li>
            <li>재입고 알림 내역</li>
            <li>최근 본 상품</li>
            <li>유즈드</li>

            <li onClick={() => setOpenModal("style")} style={{ cursor: "pointer" }}>
              나의 맞춤 정보(체형)
            </li>

            <li onClick={() => setOpenModal("profile")} style={{ cursor: "pointer" }}>
              회원정보 변경
            </li>

            <li onClick={() => setOpenModal("password")} style={{ cursor: "pointer" }}>
              비밀번호 변경
            </li>

            <li onClick={() => setOpenModal("alarm")} style={{ cursor: "pointer" }}>
              알림설정
            </li>

            <li
              onClick={() => setOpenModal("withdraw")}
              style={{ cursor: "pointer", color: "#e53935" }}
            >
              회원탈퇴
            </li>

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

{/* =========================
   모달 영역
========================= */}
{openModal && (
  <div className={styles.dim} onClick={closeModal}>
    <div
      className={`${styles.modal} ${styles.scrollModal}`}
      onClick={(e) => e.stopPropagation()}
    >

      {/* ================= 회원정보 변경 ================= */}
      {openModal === "profile" && (
        <>
          <h3>회원정보 변경</h3>

          <input
            value={profileForm.name}
            onChange={(e) =>
              setProfileForm({ ...profileForm, name: e.target.value })
            }
            placeholder="이름"
          />

          <input
            value={profileForm.phone}
            onChange={(e) =>
              setProfileForm({ ...profileForm, phone: e.target.value })
            }
            placeholder="휴대폰번호"
          />

          <div className={styles.modalButtons}>
            <button onClick={closeModal}>취소</button>
            <button onClick={handleSaveProfile}>저장</button>
          </div>
        </>
      )}

      {/* ================= 비밀번호 변경 ================= */}
      {openModal === "password" && (
        <>
          <h3>비밀번호 변경</h3>

          <input
            type="password"
            placeholder="현재 비밀번호"
            onChange={(e) =>
              setPasswordForm({
                ...passwordForm,
                currentPassword: e.target.value,
              })
            }
          />

          <input
            type="password"
            placeholder="새 비밀번호"
            onChange={(e) =>
              setPasswordForm({
                ...passwordForm,
                newPassword: e.target.value,
              })
            }
          />

          <input
            type="password"
            placeholder="비밀번호 확인"
            onChange={(e) =>
              setPasswordForm({
                ...passwordForm,
                confirmPassword: e.target.value,
              })
            }
          />

          <div className={styles.modalButtons}>
            <button onClick={closeModal}>취소</button>
            <button onClick={handleSavePassword}>저장</button>
          </div>
        </>
      )}

      {/* ================= 알림 설정 ================= */}
      {openModal === "alarm" && (
        <div className={styles.dim} onClick={closeModal}>
          <div className={styles.modal} onClick={(e)=>e.stopPropagation()}>
            <h3>알림 설정</h3>

            <div className={styles.toggleRow}>
              <span>마케팅 목적 개인정보 수집 동의</span>
              <label className={styles.switch}>
                <input
                  type="checkbox"
                  checked={alarmForm.agree_marketing}
                  onChange={(e)=>
                    setAlarmForm({...alarmForm, agree_marketing:e.target.checked})
                  }
                />
                <span className={styles.slider}></span>
              </label>
            </div>

            <div className={styles.toggleRow}>
              <span>문자 수신</span>
              <label className={styles.switch}>
                <input
                  type="checkbox"
                  checked={alarmForm.agree_sms}
                  onChange={(e)=>
                    setAlarmForm({...alarmForm, agree_sms:e.target.checked})
                  }
                />
                <span className={styles.slider}></span>
              </label>
            </div>

            <div className={styles.toggleRow}>
              <span>이메일 수신</span>
              <label className={styles.switch}>
                <input
                  type="checkbox"
                  checked={alarmForm.agree_email}
                  onChange={(e)=>
                    setAlarmForm({...alarmForm, agree_email:e.target.checked})
                  }
                />
                <span className={styles.slider}></span>
              </label>
            </div>

            <div className={styles.modalButtons}>
              <button onClick={closeModal}>취소</button>
              <button onClick={handleSaveAlarm}>저장</button>
            </div>
          </div>
        </div>
      )}

      {/* ================= 회원 탈퇴 ================= */}
      {openModal === "withdraw" && (
        <>
          <h3>회원 탈퇴</h3>

          <select
            value={withdrawReason}
            onChange={(e) => setWithdrawReason(e.target.value)}
          >
            <option value="">선택해주세요</option>
            <option>구매할 만한 상품이 없어요.</option>
            <option>상품 가격이 비싸요.</option>
            <option>배송이 느려요.</option>
            <option>교환/환불이 불편해요.</option>
            <option>혜택이 부족해요.</option>
            <option>기타</option>
          </select>

          <div className={styles.modalButtons}>
            <button onClick={closeModal}>취소</button>
            <button onClick={handleWithdraw}>탈퇴</button>
          </div>
        </>
      )}

      {/* ================= 나의 맞춤 정보 ================= */}
      {openModal === "style" && (
        <>
          <h3>나의 맞춤 정보</h3>

          <input
            name="height"
            placeholder="키 (cm)"
            value={form.height || ""}
            onChange={handleChange}
          />

          <input
            name="weight"
            placeholder="몸무게 (kg)"
            value={form.weight || ""}
            onChange={handleChange}
          />

          <button
            className={styles.toggle}
            onClick={() => setOpenUpper(!openUpper)}
          >
            상의 치수 {openUpper ? "▴" : "▾"}
          </button>

          {openUpper && (
            <>
              <input name="shoulder_width" placeholder="어깨너비" value={form.shoulder_width || ""} onChange={handleChange}/>
              <input name="chest_width" placeholder="가슴단면" value={form.chest_width || ""} onChange={handleChange}/>
              <input name="sleeve_length" placeholder="소매길이" value={form.sleeve_length || ""} onChange={handleChange}/>
              <input name="upper_total_length" placeholder="상체 총장" value={form.upper_total_length || ""} onChange={handleChange}/>
            </>
          )}

          <button
            className={styles.toggle}
            onClick={() => setOpenLower(!openLower)}
          >
            하의 치수 {openLower ? "▴" : "▾"}
          </button>

          {openLower && (
            <>
              <input name="waist_width" placeholder="허리단면" value={form.waist_width || ""} onChange={handleChange}/>
              <input name="hip_width" placeholder="엉덩이단면" value={form.hip_width || ""} onChange={handleChange}/>
              <input name="thigh_width" placeholder="허벅지단면" value={form.thigh_width || ""} onChange={handleChange}/>
              <input name="rise" placeholder="밑위" value={form.rise || ""} onChange={handleChange}/>
              <input name="hem_width" placeholder="밑단단면" value={form.hem_width || ""} onChange={handleChange}/>
              <input name="lower_total_length" placeholder="하체 총장" value={form.lower_total_length || ""} onChange={handleChange}/>
            </>
          )}

          <div className={styles.modalButtons}>
            <button onClick={closeModal}>취소</button>
            <button onClick={handleSaveStyle}>저장</button>
          </div>
        </>
      )}

    </div>
  </div>
)}
      </div>
    </div>
  );
}
