'use client';

import { useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import styles from './signup.module.css';

export default function SignupPage() {
  const router = useRouter();
  const [allChecked, setAllChecked] = useState(false);
  const [ageChecked, setAgeChecked] = useState(false);
  const [termsChecked, setTermsChecked] = useState(false);
  const [marketingChecked, setMarketingChecked] = useState(false);
  const [adsChecked, setAdsChecked] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setAllChecked(ageChecked && termsChecked && marketingChecked && adsChecked);
  }, [ageChecked, termsChecked, marketingChecked, adsChecked]);

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <h1>이용약관 동의</h1>

        <div className={styles.agreeAll}>
          <label>
            <input
              type="checkbox"
              checked={allChecked}
              onChange={(e) => {
                const checked = e.target.checked;
                setAllChecked(checked);
                setAgeChecked(checked);
                setTermsChecked(checked);
                setMarketingChecked(checked);
                setAdsChecked(checked);
                setError('');
              }}
            />
            <span>약관 전체 동의하기 (선택 동의 포함)</span>
          </label>
        </div>

        <div className={styles.checkbox}>
          <label>
            <input
              type="checkbox"
              checked={ageChecked}
              onChange={(e) => {
                setAgeChecked(e.target.checked);
                setError('');
              }}
            />
            <span>만 14세 이상 (필수)</span>
          </label>
        </div>

        <div className={styles.checkbox}>
          <label>
            <input
              type="checkbox"
              checked={termsChecked}
              onChange={(e) => {
                setTermsChecked(e.target.checked);
                setError('');
              }}
            />
            <span>서비스 이용약관 (필수)</span>
          </label>
        </div>

        <div className={styles.checkbox}>
          <label>
            <input
              type="checkbox"
              checked={marketingChecked}
              onChange={(e) => {
                setMarketingChecked(e.target.checked);
                setError('');
              }}
            />
            <span>마케팅 목적의 개인정보 수집 및 이용 동의 (선택)</span>
          </label>
        </div>

        <div className={styles.checkbox}>
          <label>
            <input
              type="checkbox"
              checked={adsChecked}
              onChange={(e) => {
                setAdsChecked(e.target.checked);
                setError('');
              }}
            />
            <span>광고성 정보 수신 동의 (선택)</span>
          </label>
        </div>

        {error && <p className={styles.error}>{error}</p>}

        <button
          className={styles.nextButton}
          onClick={() => {
            if (!ageChecked || !termsChecked) {
              setError('필수 항목에 모두 동의해야 합니다.');
              return;
            }
            router.push('/auth/register');
          }}
          disabled={!ageChecked || !termsChecked}
        >
          동의하고 계속
        </button>
      </div>
    </div>
  );
}
