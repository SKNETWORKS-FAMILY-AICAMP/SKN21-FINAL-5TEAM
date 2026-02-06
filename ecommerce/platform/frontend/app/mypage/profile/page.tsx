'use client';

import { useState } from 'react';
import styles from './profile.module.css';

type ModalType =
  | 'profile'
  | 'password'
  | 'style'
  | 'alarm'
  | 'withdraw'
  | null;

export default function ProfilePage() {
  // ✅ 임시 유저 아이디 (나중에 로그인 붙이면 교체)
  const TEMP_USER_ID = 2;

  const [openModal, setOpenModal] = useState<ModalType>(null);
  const [withdrawReason, setWithdrawReason] = useState('');

  /* =========================
     1) 회원정보 변경 state
  ========================= */
  const [profileForm, setProfileForm] = useState({
    name: '',
    email: '',
    phone: '',
  });

  /* =========================
     2) 비밀번호 변경 state
  ========================= */
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });

  /* =========================
     3) 알림 설정 state
     - DB 컬럼: agree_marketing / agree_sms / agree_email 가정
  ========================= */
  const [alarmForm, setAlarmForm] = useState({
    agree_marketing: false,
    agree_sms: false,
    agree_email: false,
  });

  /* =========================
     4) 나의 맞춤 정보 state
  ========================= */
  const [openUpper, setOpenUpper] = useState(false);
  const [openLower, setOpenLower] = useState(false);

  const [form, setForm] = useState({
    height: '',
    weight: '',
    shoulderWidth: '',
    chestWidth: '',
    sleeveLength: '',
    upperTotalLength: '',
    waistWidth: '',
    hipWidth: '',
    thighWidth: '',
    rise: '',
    hemWidth: '',
    lowerTotalLength: '',
  });

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const closeModal = () => {
    setOpenModal(null);
    setOpenUpper(false);
    setOpenLower(false);
  };

  /* =========================
     API: 나의 맞춤 정보 저장 (사장님 기존)
  ========================= */
  const handleSaveStyle = async () => {
    await fetch(`http://localhost:8000/users/${TEMP_USER_ID}/body-measurement`, {
      method: 'PUT', // 백엔드에 맞게 POST/PUT 선택
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(form),
    });

    closeModal();
  };

  /* =========================
     API: 회원 탈퇴 (사장님 기존)
  ========================= */
  const handleWithdraw = async () => {
    await fetch(`http://localhost:8000/users/${TEMP_USER_ID}`, {
      method: 'DELETE',
    });

    // TODO: 탈퇴 후 이동 (로그인 페이지 등)
  };

  /* =========================
     ✅ 추가: 회원정보 변경 저장
     - PATCH /users/{id}
  ========================= */
  const handleSaveProfile = async () => {
    await fetch(`http://localhost:8000/users/${TEMP_USER_ID}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profileForm),
    });

    closeModal();
  };

  /* =========================
     ✅ 추가: 비밀번호 변경 저장
     - PATCH /users/{id}/password
  ========================= */
  const handleSavePassword = async () => {
    // 프론트 최소 검증
    if (passwordForm.newPassword !== passwordForm.confirmPassword) return;

    await fetch(`http://localhost:8000/users/${TEMP_USER_ID}/password`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: passwordForm.currentPassword,
        new_password: passwordForm.newPassword,
      }),
    });

    closeModal();
  };

  /* =========================
     ✅ 추가: 알림 설정 저장
     - PATCH /users/{id}
     - agree_marketing / agree_sms / agree_email 업데이트
  ========================= */
  const handleSaveAlarm = async () => {
    await fetch(`http://localhost:8000/users/${TEMP_USER_ID}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(alarmForm),
    });

    closeModal();
  };

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <h2 className={styles.title}>설정</h2>

        {/* 프로필 */}
        <div className={styles.profileBox}>
          <div className={styles.avatar} />
          <div>
            <strong className={styles.userName}>윈터는 이쁘다</strong>
            <p className={styles.userId}>ID: abcd1234</p>
          </div>
        </div>

        <div className={styles.buttonRow}>
          <button className={styles.outlineBtn}>프로필 이미지 변경</button>
          <button className={styles.outlineBtn}>닉네임 변경</button>
        </div>

        {/* 메뉴 */}
        <ul className={styles.menuList}>
          <li className={styles.menuItem} onClick={() => setOpenModal('profile')}>
            <strong>회원정보 변경</strong>
            <span className={styles.arrow}>›</span>
          </li>
          <li className={styles.menuItem} onClick={() => setOpenModal('password')}>
            <strong>비밀번호 변경</strong>
            <span className={styles.arrow}>›</span>
          </li>
          <li className={styles.menuItem} onClick={() => setOpenModal('style')}>
            <strong>나의 맞춤 정보</strong>
            <span className={styles.arrow}>›</span>
          </li>
          <li className={styles.menuItem} onClick={() => setOpenModal('alarm')}>
            <strong>알림 설정</strong>
            <span className={styles.arrow}>›</span>
          </li>
          <li className={styles.menuItem} onClick={() => setOpenModal('withdraw')}>
            <strong>회원 탈퇴</strong>
            <span className={styles.arrow}>›</span>
          </li>
        </ul>

        {/* ===== 모달 ===== */}
        {openModal && (
          <>
            <div className={styles.dim} onClick={closeModal} />

            {/* ===== 나의 맞춤 정보 (스크롤 적용 핵심) ===== */}
            {openModal === 'style' && (
              <div
                className={`${styles.modal} ${styles.scrollModal}`}
                onClick={(e) => e.stopPropagation()}
              >
                <h3>나의 맞춤 정보</h3>

                <div className={styles.section}>
                  <input
                    className={styles.input}
                    name="height"
                    placeholder="키 (cm)"
                    value={form.height}
                    onChange={handleChange}
                  />
                  <input
                    className={styles.input}
                    name="weight"
                    placeholder="몸무게 (kg)"
                    value={form.weight}
                    onChange={handleChange}
                  />
                </div>

                <button
                  className={styles.toggle}
                  onClick={() => setOpenUpper(!openUpper)}
                >
                  상의 치수 {openUpper ? '▴' : '▾'}
                </button>

                {openUpper && (
                  <div className={styles.section}>
                    <input className={styles.input} name="shoulderWidth" placeholder="어깨너비 (cm)" value={form.shoulderWidth} onChange={handleChange} />
                    <input className={styles.input} name="chestWidth" placeholder="가슴단면 (cm)" value={form.chestWidth} onChange={handleChange} />
                    <input className={styles.input} name="sleeveLength" placeholder="소매길이 (cm)" value={form.sleeveLength} onChange={handleChange} />
                    <input className={styles.input} name="upperTotalLength" placeholder="상체 총장 (cm)" value={form.upperTotalLength} onChange={handleChange} />
                  </div>
                )}

                <button
                  className={styles.toggle}
                  onClick={() => setOpenLower(!openLower)}
                >
                  하의 치수 {openLower ? '▴' : '▾'}
                </button>

                {openLower && (
                  <div className={styles.section}>
                    <input className={styles.input} name="waistWidth" placeholder="허리단면 (cm)" value={form.waistWidth} onChange={handleChange} />
                    <input className={styles.input} name="hipWidth" placeholder="엉덩이단면 (cm)" value={form.hipWidth} onChange={handleChange} />
                    <input className={styles.input} name="thighWidth" placeholder="허벅지단면 (cm)" value={form.thighWidth} onChange={handleChange} />
                    <input className={styles.input} name="rise" placeholder="밑위 (cm)" value={form.rise} onChange={handleChange} />
                    <input className={styles.input} name="hemWidth" placeholder="밑단단면 (cm)" value={form.hemWidth} onChange={handleChange} />
                    <input className={styles.input} name="lowerTotalLength" placeholder="하체 총장 (cm)" value={form.lowerTotalLength} onChange={handleChange} />
                  </div>
                )}

                <div className={styles.modalButtons}>
                  <button className={styles.cancel} onClick={closeModal}>취소</button>
                  <button className={styles.confirm} onClick={handleSaveStyle}>저장</button>
                </div>
              </div>
            )}

            {/* ===== 공통 모달 ===== */}
            {openModal !== 'style' && (
              <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                {openModal === 'profile' && (
                  <>
                    <h3>회원정보 변경</h3>
                    <input
                      placeholder="이름"
                      value={profileForm.name}
                      onChange={(e) => setProfileForm((p) => ({ ...p, name: e.target.value }))}
                    />
                    <input
                      placeholder="이메일"
                      value={profileForm.email}
                      onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))}
                    />
                    <input
                      placeholder="휴대폰번호"
                      value={profileForm.phone}
                      onChange={(e) => setProfileForm((p) => ({ ...p, phone: e.target.value }))}
                    />
                  </>
                )}

                {openModal === 'password' && (
                  <>
                    <h3>비밀번호 변경</h3>
                    <input
                      type="password"
                      placeholder="현재 비밀번호"
                      value={passwordForm.currentPassword}
                      onChange={(e) => setPasswordForm((p) => ({ ...p, currentPassword: e.target.value }))}
                    />
                    <input
                      type="password"
                      placeholder="새 비밀번호"
                      value={passwordForm.newPassword}
                      onChange={(e) => setPasswordForm((p) => ({ ...p, newPassword: e.target.value }))}
                    />
                    <input
                      type="password"
                      placeholder="비밀번호 확인"
                      value={passwordForm.confirmPassword}
                      onChange={(e) => setPasswordForm((p) => ({ ...p, confirmPassword: e.target.value }))}
                    />
                  </>
                )}

                {openModal === 'alarm' && (
                  <>
                    <h3>알림 설정</h3>
                    <div className={styles.toggleRow}>
                      <span>마케팅 목적 개인정보 수집 동의</span>
                      <input
                        type="checkbox"
                        checked={alarmForm.agree_marketing}
                        onChange={(e) => setAlarmForm((a) => ({ ...a, agree_marketing: e.target.checked }))}
                      />
                    </div>
                    <div className={styles.toggleRow}>
                      <span>문자 수신</span>
                      <input
                        type="checkbox"
                        checked={alarmForm.agree_sms}
                        onChange={(e) => setAlarmForm((a) => ({ ...a, agree_sms: e.target.checked }))}
                      />
                    </div>
                    <div className={styles.toggleRow}>
                      <span>이메일 수신</span>
                      <input
                        type="checkbox"
                        checked={alarmForm.agree_email}
                        onChange={(e) => setAlarmForm((a) => ({ ...a, agree_email: e.target.checked }))}
                      />
                    </div>
                  </>
                )}

                {openModal === 'withdraw' && (
                  <>
                    <h3>회원 탈퇴</h3>
                    <p className={styles.desc}>탈퇴 사유를 선택해 주세요.</p>
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
                  </>
                )}

                <div className={styles.modalButtons}>
                  <button className={styles.cancel} onClick={closeModal}>
                    취소
                  </button>

                  {openModal === 'withdraw' ? (
                    <button
                      className={styles.confirm}
                      onClick={handleWithdraw}
                      disabled={!withdrawReason}
                    >
                      다음
                    </button>
                  ) : (
                    <button
                      className={styles.confirm}
                      onClick={
                        openModal === 'profile'
                          ? handleSaveProfile
                          : openModal === 'password'
                          ? handleSavePassword
                          : openModal === 'alarm'
                          ? handleSaveAlarm
                          : closeModal
                      }
                      disabled={
                        openModal === 'password' &&
                        (!!passwordForm.newPassword &&
                          passwordForm.newPassword !== passwordForm.confirmPassword)
                      }
                    >
                      저장
                    </button>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
