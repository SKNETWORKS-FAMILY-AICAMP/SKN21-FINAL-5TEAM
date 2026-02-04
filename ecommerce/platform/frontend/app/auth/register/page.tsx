'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './register.module.css';

const PASSWORD_REGEX = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,16}$/;

export default function RegisterPage() {
  const router = useRouter();

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
  const [address1, setAddress1] = useState('');
  const [address2, setAddress2] = useState('');

  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function checkEmail() {
    setFormError('');
    if (!email) {
      setFormError('이메일을 입력해 주세요.');
      return;
    }
    setCheckingEmail(true);
    try {
      const res = await fetch('/api/auth/check-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      setEmailChecked(true);
      setEmailAvailable(Boolean(data.available));
    } catch (err) {
      setFormError('중복확인 중 오류가 발생했습니다.');
    } finally {
      setCheckingEmail(false);
    }
  }

  function handlePhoneChange(v: string) {
    // Allow only digits (remove '-')
    const digits = v.replace(/\D/g, '');
    setPhone(digits);
  }

  function validatePassword() {
    return PASSWORD_REGEX.test(password);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');

    if (!email) return setFormError('이메일을 입력해 주세요.');
    if (!emailChecked || emailAvailable !== true) return setFormError('이메일 중복확인을 해주세요.');
    if (!validatePassword()) return setFormError('비밀번호 규칙을 확인해 주세요.');
    if (password !== passwordConfirm) return setFormError('비밀번호가 일치하지 않습니다.');
    if (!name) return setFormError('이름을 입력해 주세요.');
    if (dob && dob.length !== 8) return setFormError('생년월일은 8자리로 입력해 주세요.');
    if (phone && phone.length < 9) return setFormError('전화번호를 올바르게 입력해 주세요.');

    setSubmitting(true);
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name, dob, phone, address1, address2 }),
      });
      if (res.ok) {
        // 성공하면 로그인 페이지로 이동
        router.push('/auth/login');
      } else {
        const data = await res.json();
        setFormError(data?.error || '회원가입 중 오류가 발생했습니다.');
      }
    } catch (err) {
      setFormError('서버와 통신할 수 없습니다.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>회원가입</h1>

      <form className={styles.form} onSubmit={handleSubmit}>
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
              placeholder="example@domain.com"
            />
            <button type="button" onClick={checkEmail} disabled={checkingEmail}>
              {checkingEmail ? '확인 중...' : '중복확인'}
            </button>
          </div>
          {emailChecked && (
            <div className={emailAvailable ? styles.success : styles.error}>
              {emailAvailable ? '사용 가능한 이메일입니다.' : '이미 사용 중인 이메일입니다.'}
            </div>
          )}
        </div>

        <div className={styles.field}>
          <label>비밀번호</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setPasswordTouched(true)}
          />
          <div className={styles.smallText}>비밀번호: 8~16자의 영문 소문자, 숫자, 특수문자</div>
          {passwordTouched && !validatePassword() && (
            <div className={styles.error}>비밀번호가 규칙에 맞지 않습니다.</div>
          )}
        </div>

        <div className={styles.field}>
          <label>비밀번호 확인</label>
          <input type="password" value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)} />
        </div>

        <div className={styles.field}>
          <label>이름</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className={styles.field}>
          <label>생년월일</label>
          <input placeholder="생년월일 8자리" value={dob} onChange={(e) => setDob(e.target.value.replace(/\D/g, '').slice(0, 8))} />
        </div>

        <div className={styles.field}>
          <label>전화번호</label>
          <input value={phone} onChange={(e) => handlePhoneChange(e.target.value)} placeholder="- 을 제외한 전화번호" />
        </div>

        <div className={styles.field}>
          <label>주소</label>
          <input placeholder="기본 주소" value={address1} onChange={(e) => setAddress1(e.target.value)} />
          <input placeholder="상세 주소" value={address2} onChange={(e) => setAddress2(e.target.value)} />
        </div>

        {formError && <div className={styles.error}>{formError}</div>}

        <button className={styles.submit} type="submit" disabled={submitting}>
          {submitting ? '가입 중...' : '회원가입 완료'}
        </button>
      </form>
    </div>
  );
}

