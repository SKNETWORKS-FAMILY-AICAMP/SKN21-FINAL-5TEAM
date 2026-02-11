'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './profile.module.css';

type ModalType =
  | 'profile'
  | 'password'
  | 'style'
  | 'alarm'
  | 'withdraw'
  | null;

export default function ProfilePage() {
  const router = useRouter();

  const [openModal, setOpenModal] = useState<ModalType>(null);
  const [withdrawReason, setWithdrawReason] = useState('');

  const [user, setUser] = useState<any>(null);

  /* =========================
     로그인 가드 + 유저 정보 로드
  ========================= */
  useEffect(() => {
    fetch('http://localhost:8000/users/me', {
      credentials: 'include',
    })
      .then(async (res) => {
        if (!res.ok) {
          router.replace('/auth/login');
          return;
        }
        const data = await res.json();
        setUser(data);

        setProfileForm({
          name: data.name ?? '',
          phone: data.phone ?? '',
        });

        setAlarmForm({
          agree_marketing: Boolean(data.agree_marketing),
          agree_sms: Boolean(data.agree_sms),
          agree_email: Boolean(data.agree_email),
        });
      })
      .catch(() => {
        router.replace('/auth/login');
      });
  }, [router]);

  /* =========================
     회원정보 변경
  ========================= */
  const [profileForm, setProfileForm] = useState({
    name: '',
    phone: '',
  });

  const handleSaveProfile = async () => {
    await fetch(`http://localhost:8000/users/me`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profileForm),
    });
    closeModal();
  };

  /* =========================
     비밀번호 변경
  ========================= */
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });

  const handleSavePassword = async () => {
    if (passwordForm.newPassword !== passwordForm.confirmPassword) return;

    await fetch(`http://localhost:8000/users/me/password`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
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
    await fetch(`http://localhost:8000/users/me`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(alarmForm),
    });

    closeModal();
  };

  /* =========================
     나의 맞춤 정보
  ========================= */
  const [openUpper, setOpenUpper] = useState(false);
  const [openLower, setOpenLower] = useState(false);

  const [form, setForm] = useState({
    height: '',
    weight: '',
    shoulder_width: '',
    chest_width: '',
    sleeve_length: '',
    upper_total_length: '',
    waist_width: '',
    hip_width: '',
    thigh_width: '',
    rise: '',
    hem_width: '',
    lower_total_length: '',
  });

  // const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
  //   const { name, value } = e.target;
  //   setForm((prev) => ({ ...prev, [name]: value }));
  // };

  // const handleSaveStyle = async () => {
  //   await fetch(`http://localhost:8000/users/me/body-measurement`, {
  //     method: 'PUT',
  //     credentials: 'include',
  //     headers: { 'Content-Type': 'application/json' },
  //     body: JSON.stringify(form),
  //   });
  //   closeModal();
  // };

    /* =========================
     BodyMeasurement 로드
  ========================= */
  const loadBodyMeasurement = async () => {
    const res = await fetch(
      'http://localhost:8000/users/me/body-measurement',
      { credentials: 'include' }
    );

    if (!res.ok) return;

    const data = await res.json();

    setForm({
      height: data.height ?? '',
      weight: data.weight ?? '',
      shoulder_width: data.shoulder_width ?? '',
      chest_width: data.chest_width ?? '',
      sleeve_length: data.sleeve_length ?? '',
      upper_total_length: data.upper_total_length ?? '',
      waist_width: data.waist_width ?? '',
      hip_width: data.hip_width ?? '',
      thigh_width: data.thigh_width ?? '',
      rise: data.rise ?? '',
      hem_width: data.hem_width ?? '',
      lower_total_length: data.lower_total_length ?? '',
    });
  };

  /* =========================
     모달 열릴 때 자동 로드
  ========================= */
  useEffect(() => {
    if (openModal === 'style') {
      loadBodyMeasurement();
    }
  }, [openModal]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSaveStyle = async () => {
    await fetch('http://localhost:8000/users/me/body-measurement', {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });

    await loadBodyMeasurement();
    setOpenModal(null);
  };

  if (!user) return null;

  /* =========================
     회원 탈퇴
  ========================= */
  const handleWithdraw = async () => {
    await fetch('http://localhost:8000/users/me', {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reason: withdrawReason,
      }),
    });

    router.replace('/auth/login');
  };

  /* =========================
     로그아웃
  ========================= */
  const handleLogout = async () => {
    await fetch('http://localhost:8000/users/logout', {
      method: 'POST',
      credentials: 'include',
    });

    router.replace('/auth/login');
  };

  const closeModal = () => {
    setOpenModal(null);
    setOpenUpper(false);
    setOpenLower(false);
  };

  if (!user) return null;

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <h2 className={styles.title}>설정</h2>

        <div className={styles.profileBox}>
          <div className={styles.avatar} />
          <div>
            <strong className={styles.userName}>{user.name}</strong>
            <p className={styles.userId}>ID: {user.email}</p>
          </div>
        </div>

        <div className={styles.buttonRow}>
          <button className={styles.outlineBtn}>프로필 이미지 변경</button>
          <button className={styles.outlineBtn}>닉네임 변경</button>
        </div>

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

        <div className={styles.footer}>
          <button type="button" onClick={handleLogout}>
            <span className={styles.logoutText}>로그아웃</span>
          </button>
        </div>
        {openModal && (
  <>
    <div className={styles.dim} onClick={closeModal} />

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
          onClick={() => setOpenUpper((v) => !v)}
        >
          상의 치수 {openUpper ? '▴' : '▾'}
        </button>

        {openUpper && (
          <div className={styles.section}>
            <input className={styles.input} name="shoulder_width" placeholder="어깨너비"  value={form.shoulder_width} onChange={handleChange} />
            <input className={styles.input} name="chest_width" placeholder="가슴단면" value={form.chest_width} onChange={handleChange} />
            <input className={styles.input} name="sleeve_length" placeholder="소매길이" value={form.sleeve_length} onChange={handleChange} />
            <input className={styles.input} name="upper_total_length" placeholder="상체 총장" value={form.upper_total_length} onChange={handleChange} />
          </div>
        )}

        <button
          className={styles.toggle}
          onClick={() => setOpenLower((v) => !v)}
        >
          하의 치수 {openLower ? '▴' : '▾'}
        </button>

        {openLower && (
          <div className={styles.section}>
            <input className={styles.input} name="waist_width" placeholder="허리단면" value={form.waist_width} onChange={handleChange} />
            <input className={styles.input} name="hip_width" placeholder="엉덩이단면" value={form.hip_width} onChange={handleChange} />
            <input className={styles.input} name="thigh_width" placeholder="허벅지단면" value={form.thigh_width} onChange={handleChange} />
            <input className={styles.input} name="rise" placeholder="밑위" value={form.rise} onChange={handleChange} />
            <input className={styles.input} name="hem_width" placeholder="밑단단면" value={form.hem_width} onChange={handleChange} />
            <input className={styles.input} name="lower_total_length" placeholder="하체 총장" value={form.lower_total_length} onChange={handleChange} />
          </div>
        )}

        <div className={styles.modalButtons}>
          <button className={styles.cancel} onClick={closeModal}>
            취소
          </button>
          <button className={styles.confirm} onClick={handleSaveStyle}>
            저장
          </button>
        </div>
      </div>
    )}

    {openModal !== 'style' && (
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {openModal === 'profile' && (
          <>
            <h3>회원정보 변경</h3>
            <input
              placeholder="이름"
              value={profileForm.name}
              onChange={(e) =>
                setProfileForm((p) => ({ ...p, name: e.target.value }))
              }
            />
            <input
              placeholder="휴대폰번호"
              value={profileForm.phone}
              onChange={(e) =>
                setProfileForm((p) => ({ ...p, phone: e.target.value }))
              }
            />
          </>
        )}

        {openModal === 'password' && (
          <>
            <h3>비밀번호 변경</h3>
            <input type="password" placeholder="현재 비밀번호"
              value={passwordForm.currentPassword}
              onChange={(e) =>
                setPasswordForm((p) => ({ ...p, currentPassword: e.target.value }))
              }
            />
            <input type="password" placeholder="새 비밀번호"
              value={passwordForm.newPassword}
              onChange={(e) =>
                setPasswordForm((p) => ({ ...p, newPassword: e.target.value }))
              }
            />
            <input type="password" placeholder="비밀번호 확인"
              value={passwordForm.confirmPassword}
              onChange={(e) =>
                setPasswordForm((p) => ({ ...p, confirmPassword: e.target.value }))
              }
            />
          </>
        )}

        {openModal === 'alarm' && (
          <>
            <h3>알림 설정</h3>
            <div className={styles.toggleRow}>
              <span>마케팅 목적 개인정보 수집 동의</span>
              <input type="checkbox"
                checked={alarmForm.agree_marketing}
                onChange={(e) =>
                  setAlarmForm((a) => ({ ...a, agree_marketing: e.target.checked }))
                }
              />
            </div>
            <div className={styles.toggleRow}>
              <span>문자 수신</span>
              <input type="checkbox"
                checked={alarmForm.agree_sms}
                onChange={(e) =>
                  setAlarmForm((a) => ({ ...a, agree_sms: e.target.checked }))
                }
              />
            </div>
            <div className={styles.toggleRow}>
              <span>이메일 수신</span>
              <input type="checkbox"
                checked={alarmForm.agree_email}
                onChange={(e) =>
                  setAlarmForm((a) => ({ ...a, agree_email: e.target.checked }))
                }
              />
            </div>
          </>
        )}

        {openModal === 'withdraw' && (
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
          </>
        )}

        <div className={styles.modalButtons}>
          <button className={styles.cancel} onClick={closeModal}>
            취소
          </button>
          <button
            className={styles.confirm}
            onClick={
              openModal === 'profile'
                ? handleSaveProfile
                : openModal === 'password'
                ? handleSavePassword
                : openModal === 'alarm'
                ? handleSaveAlarm
                : openModal === 'withdraw'
                ? handleWithdraw
                : closeModal
            }
          >
            저장
          </button>
        </div>
      </div>
    )}
  </>
)}

      </div>
    </div>
  );
}
