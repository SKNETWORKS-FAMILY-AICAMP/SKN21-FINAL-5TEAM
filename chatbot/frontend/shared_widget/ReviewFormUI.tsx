'use client';

import React, { useState } from 'react';
import styles from './reviewform.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_CHATBOT_API_URL || 'http://localhost:8100';

interface ReviewFormUIProps {
  orderId: string;
  productId: string;
  productName: string;
  onSubmit: (payload: { rating: number; content: string; order_id: string; product_id: string }) => void;
  onCancel?: () => void;
}

type Satisfaction = '좋음' | '보통' | '아쉬움';

export default function ReviewFormUI({
  orderId,
  productId,
  productName,
  onSubmit,
  onCancel,
}: ReviewFormUIProps) {
  const [satisfaction, setSatisfaction] = useState<Satisfaction | null>(null);
  const [content, setContent] = useState('');
  const [isDrafting, setIsDrafting] = useState(false);
  const [draftCache, setDraftCache] = useState<Record<string, string[]>>({});
  const [currentDrafts, setCurrentDrafts] = useState<string[]>([]);
  const [draftError, setDraftError] = useState<string | null>(null);

  // Map satisfaction to rating (5, 3, 1)
  const getRating = (sat: Satisfaction): number => {
    switch (sat) {
      case '좋음': return 5;
      case '보통': return 3;
      case '아쉬움': return 1;
      default: return 5;
    }
  };

  const handleSatisfactionClick = async (sat: Satisfaction) => {
    setSatisfaction(sat);
    setDraftError(null);

    // If we already have drafts for this satisfaction, use cache
    if (draftCache[sat]) {
      setCurrentDrafts(draftCache[sat]);
      return;
    }

    // Otherwise, fetch from backend API
    setIsDrafting(true);
    setCurrentDrafts([]);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/review-draft`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          product_name: productName,
          satisfaction: sat,
          keywords: []
        }),
      });

      if (!response.ok) {
        throw new Error('초안 생성 API 호출 실패');
      }

      const data = await response.json();
      if (data.success && data.drafts) {
        // Collect shorts, emotional, detailed into an array
        const drafts = [
          data.drafts.short,
          data.drafts.emotional,
          data.drafts.detailed
        ].filter(Boolean) as string[];

        setDraftCache((prev) => ({ ...prev, [sat]: drafts }));
        setCurrentDrafts(drafts);
      } else {
        throw new Error(data.error || '초안 생성에 실패했습니다.');
      }
    } catch (err: unknown) {
      console.error(err);
      setDraftError('리뷰 초안을 불러오지 못했습니다. 직접 입력해주세요.');
    } finally {
      setIsDrafting(false);
    }
  };

  const handleSubmit = () => {
    if (!satisfaction) {
      alert('만족도를 선택해주세요.');
      return;
    }
    if (!content.trim()) {
      alert('리뷰 내용을 입력해주세요.');
      return;
    }

    onSubmit({
      rating: getRating(satisfaction),
      content,
      order_id: orderId,
      product_id: productId,
    });
  };

  return (
    <div className={styles.reviewFormContainer}>
      <h3 className={styles.title}>리뷰 작성</h3>
      <p className={styles.subtitle}>
        <strong>{productName}</strong> 상품은 어떠셨나요?
      </p>

      {/* Satisfaction Buttons */}
      <div className={styles.satisfactionGroup}>
        {(['좋음', '보통', '아쉬움'] as Satisfaction[]).map((sat) => (
          <button
            key={sat}
            className={`${styles.satisfactionBtn} ${satisfaction === sat ? styles.activeBtn : ''}`}
            onClick={() => handleSatisfactionClick(sat)}
          >
            {sat === '좋음' && '😄 '}
            {sat === '보통' && '😐 '}
            {sat === '아쉬움' && '😞 '}
            {sat}
          </button>
        ))}
      </div>

      {/* Drafts Section */}
      {satisfaction && (
        <div className={styles.draftSection}>
          {isDrafting && <p className={styles.loadingDrafts}>AI가 리뷰 초안을 작성 중입니다...</p>}
          {draftError && <p className={styles.errorText}>{draftError}</p>}
          
          {!isDrafting && currentDrafts.length > 0 && (
            <div className={styles.draftList}>
              <p className={styles.draftPrompt}>추천 리뷰 (클릭하여 텍스트 상자에 적용)</p>
              {currentDrafts.map((draft, idx) => (
                <button
                  key={idx}
                  className={styles.draftItemBtn}
                  onClick={() => setContent(draft)}
                >
                  &quot;{draft}&quot;
                </button>
              ))}
            </div>
          )}

          {/* Text Area */}
          <textarea
            className={styles.textArea}
            placeholder="상품에 대한 솔직한 리뷰를 남겨주세요."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
          />

          <div className={styles.actionGroup}>
            {onCancel && (
              <button className={styles.cancelBtn} onClick={onCancel}>
                취소
              </button>
            )}
            <button className={styles.submitBtn} onClick={handleSubmit}>
              리뷰 등록
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
