'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import styles from './register.module.css';

const PASSWORD_REGEX =
  /^(?=.{8,16}$)(?=.*[a-z])(?=.*\d)(?=.*[^A-Za-z0-9]).*$/;

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;

/**
 * 인증 액션을 user history에 기록
 */
async function trackAuthAction(
  userId: number,
  actionType: 'login' | 'logout' | 'register'
): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/user-history/users/${userId}/track/auth`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        action_type: actionType,
      }),
    });
    console.log(`User history tracked: ${actionType} for user ${userId}`);
  } catch (err) {
    console.error('Failed to track auth action:', err);
    // 히스토리 기록 실패는 무시 (사용자 경험에 영향 없음)
  }
}

function RegisterPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // signup에서 넘어온 약관 동의 값
  const agreeMarketing =
    searchParams.get('marketing') === 'true';
  const agreeAds =
    searchParams.get('ads') === 'true';

  // ===== state =====
  const [email, setEmail] = useState('');
  const [emailChecked, setEmailChecked] = useState(false);
  const [emailAvailable, setEmailAvailable] = useState<boolean | null>(null);
  const [checkingEmail, setCheckingEmail] = useState(false);

  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [passwordTouched, setPasswordTouched] = useState(false);

  const [name, setName] = useState('');
  const [dob, setDob] = useState('');
  const [phone, setPhone] = useState('');

  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // ===== util =====
  const validatePassword = () => PASSWORD_REGEX.test(password);

  const handlePhoneChange = (v: string) => {
    setPhone(v.replace(/\D/g, ''));
  };

  // ===== 이메일 중복 확인 =====
  async function checkEmail() {
    if (!email) {
      setFormError('이메일을 입력해 주세요.');
      return;
    }

    setFormError('');
    setCheckingEmail(true);

    try {
      const res = await fetch(`${API_BASE_URL}/users/check-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      const data = await res.json();
      setEmailChecked(true);
      setEmailAvailable(Boolean(data.available));
    } catch {
      setFormError('이메일 중복 확인 중 오류가 발생했습니다.');
    } finally {
      setCheckingEmail(false);
    }
  }

  // ===== 회원가입 =====
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');

    if (!email) return setFormError('이메일을 입력해 주세요.');
    if (!emailChecked || emailAvailable !== true)
      return setFormError('이메일 중복확인을 해주세요.');
    if (!validatePassword())
      return setFormError('비밀번호 규칙을 확인해 주세요.');
    if (password !== passwordConfirm)
      return setFormError('비밀번호가 일치하지 않습니다.');
    if (!name) return setFormError('이름을 입력해 주세요.');

    setSubmitting(true);

    try {
      const res = await fetch(`${API_BASE_URL}/users/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          password,
          name,
          phone,
          agree_marketing_info: agreeMarketing,
          agree_ad_sms: agreeAds,
          agree_ad_email: agreeAds,
        }),
      });

      if (res.ok) {
        const data = await res.json();

        // User History에 회원가입 기록
        if (data.user_id || data.id) {
          await trackAuthAction(data.user_id || data.id, 'register');
        }

        router.push('/auth/login');
      } else {
        const data = await res.json();
        setFormError(data?.detail || '회원가입에 실패했습니다.');
      }
    } catch {
      setFormError('서버와 통신할 수 없습니다.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>회원가입</h1>

      <form className={styles.form} onSubmit={handleSubmit}>
        {/* 이메일 */}
        <div className={styles.field}>
          <label>이메일</label>
          <div className={styles.inline}>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value.trim());
                setEmailChecked(false);
                setEmailAvailable(null);
              }}
              placeholder="example@email.com"
            />
            <button type="button" onClick={checkEmail} disabled={checkingEmail}>
              {checkingEmail ? '확인 중' : '중복확인'}
            </button>
          </div>
          {emailChecked && (
            <p className={emailAvailable ? styles.success : styles.error}>
              {emailAvailable
                ? '사용 가능한 이메일입니다.'
                : '이미 사용 중인 이메일입니다.'}
            </p>
          )}
        </div>

        {/* 비밀번호 */}
        <div className={styles.field}>
          <label>비밀번호</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setPasswordTouched(true)}
          />
          <div className={styles.smallText}>
            비밀번호: 8~16자의 영문 소문자, 숫자, 특수문자
          </div>
          {passwordTouched && !validatePassword() && (
            <p className={styles.error}>비밀번호 규칙을 확인해 주세요.</p>
          )}
        </div>

        {/* 비밀번호 확인 */}
        <div className={styles.field}>
          <label>비밀번호 확인</label>
          <input
            type="password"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
          />
        </div>

        {/* 이름 */}
        <div className={styles.field}>
          <label>이름</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        {/* 생년월일 (UI용) */}
        <div className={styles.field}>
          <label>생년월일</label>
          <input
            placeholder="YYYYMMDD"
            value={dob}
            onChange={(e) =>
              setDob(e.target.value.replace(/\D/g, '').slice(0, 8))
            }
          />
        </div>

        {/* 전화번호 */}
        <div className={styles.field}>
          <label>전화번호</label>
          <input
            value={phone}
            onChange={(e) => handlePhoneChange(e.target.value)}
            placeholder="- 없이 숫자만 입력"
          />
        </div>

        {formError && <p className={styles.error}>{formError}</p>}

        <button className={styles.submit} type="submit" disabled={submitting}>
          {submitting ? '가입 중...' : '회원가입 완료'}
        </button>
      </form>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterPageContent />
    </Suspense>
  );
}
