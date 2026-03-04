'use client';

import { useMemo, useState } from 'react';
import styles from './usedsaleform.module.css';

type ConditionOption = {
  id: number;
  name: string;
  description?: string | null;
};

type CategoryOption = {
  id: number;
  name: string;
};

type UsedSaleFormUIProps = {
  message?: string;
  categoryOptions?: CategoryOption[];
  conditionOptions?: ConditionOption[];
  categoryPlaceholder?: string;
  itemNamePlaceholder?: string;
  descriptionPlaceholder?: string;
  pricePlaceholder?: string;
  onSubmit: (payload: {
    category_id: number;
    category: string;
    item_name: string;
    description: string;
    condition_id: number;
    condition: string;
    expected_price?: number | null;
  }) => void;
};

export default function UsedSaleFormUI({
  message = '중고 판매 정보를 입력해주세요.',
  categoryOptions,
  conditionOptions,
  categoryPlaceholder = '카테고리를 선택하세요',
  itemNamePlaceholder = '예: 나이키 후드집업',
  descriptionPlaceholder = '상품 상태, 사용감, 하자 여부 등을 입력하세요',
  pricePlaceholder = '예: 30000',
  onSubmit,
}: UsedSaleFormUIProps) {
  const resolvedConditionOptions = useMemo<ConditionOption[]>(() => {
    const defaults: ConditionOption[] = [
      { id: 1, name: 'S급' },
      { id: 2, name: 'A급' },
      { id: 3, name: 'B급' },
    ];
    if (!conditionOptions || conditionOptions.length === 0) return defaults;

    const normalized = conditionOptions
      .filter((item) => Number.isFinite(item.id) && item.id > 0 && item.name?.trim().length > 0)
      .map((item) => ({ id: item.id, name: item.name.trim(), description: item.description ?? null }));

    return normalized.length ? normalized : defaults;
  }, [conditionOptions]);

  const resolvedCategoryOptions = useMemo<CategoryOption[]>(() => {
    if (!categoryOptions || categoryOptions.length === 0) return [];
    return categoryOptions
      .filter((item) => Number.isFinite(item.id) && item.id > 0 && item.name?.trim().length > 0)
      .map((item) => ({ id: item.id, name: item.name.trim() }));
  }, [categoryOptions]);

  const [selectedCategoryId, setSelectedCategoryId] = useState<number>(resolvedCategoryOptions[0]?.id ?? 0);
  const [selectedCategoryName, setSelectedCategoryName] = useState<string>(resolvedCategoryOptions[0]?.name ?? '');
  const [itemName, setItemName] = useState('');
  const [description, setDescription] = useState('');
  const [condition, setCondition] = useState<ConditionOption>(resolvedConditionOptions[0]);
  const [expectedPrice, setExpectedPrice] = useState('');
  const [isSubmitted, setIsSubmitted] = useState(false);

  const submit = () => {
    if (isSubmitted) return;

    const trimmedItemName = itemName.trim();
    const trimmedDescription = description.trim();

    if (!selectedCategoryId) {
      alert('카테고리를 선택해주세요.');
      return;
    }

    if (!trimmedItemName) {
      alert('상품명을 입력해주세요.');
      return;
    }

    if (!trimmedDescription) {
      alert('상품 설명을 입력해주세요.');
      return;
    }

    const numericPrice = expectedPrice.trim() ? Number(expectedPrice.trim()) : null;
    if (numericPrice !== null && (!Number.isFinite(numericPrice) || numericPrice < 0)) {
      alert('희망 가격은 0 이상의 숫자로 입력해주세요.');
      return;
    }

    onSubmit({
      category_id: selectedCategoryId,
      category: selectedCategoryName,
      item_name: trimmedItemName,
      description: trimmedDescription,
      condition_id: condition.id,
      condition: condition.name,
      expected_price: numericPrice,
    });

    setIsSubmitted(true);
  };

  return (
    <div className={styles.container}>
      <div className={styles.title}>{message}</div>

      <label className={styles.label}>카테고리</label>
      {resolvedCategoryOptions.length > 0 ? (
        <select
          className={styles.input}
          value={selectedCategoryId || ''}
          onChange={(e) => {
            const id = Number(e.target.value);
            const selected = resolvedCategoryOptions.find((item) => item.id === id);
            setSelectedCategoryId(id);
            setSelectedCategoryName(selected?.name ?? '');
          }}
          disabled={isSubmitted}
        >
          {resolvedCategoryOptions.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          className={styles.input}
          value={selectedCategoryName}
          onChange={(e) => setSelectedCategoryName(e.target.value)}
          placeholder={categoryPlaceholder}
          disabled={isSubmitted}
        />
      )}

      <label className={styles.label}>상품명</label>
      <input
        type="text"
        className={styles.input}
        value={itemName}
        onChange={(e) => setItemName(e.target.value)}
        placeholder={itemNamePlaceholder}
        disabled={isSubmitted}
      />

      <label className={styles.label}>설명</label>
      <textarea
        className={styles.textarea}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder={descriptionPlaceholder}
        rows={4}
        disabled={isSubmitted}
      />

      <label className={styles.label}>상태</label>
      <div className={styles.conditionGroup}>
        {resolvedConditionOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`${styles.conditionBtn} ${condition.id === option.id ? styles.activeBtn : ''}`}
            onClick={() => setCondition(option)}
            disabled={isSubmitted}
            title={option.description || undefined}
          >
            {option.name}
          </button>
        ))}
      </div>

      <label className={styles.label}>희망 가격 (선택)</label>
      <input
        type="number"
        min={0}
        className={styles.input}
        value={expectedPrice}
        onChange={(e) => setExpectedPrice(e.target.value)}
        placeholder={pricePlaceholder}
        disabled={isSubmitted}
      />

      <button type="button" className={styles.submitBtn} onClick={submit} disabled={isSubmitted}>
        {isSubmitted ? '중고 판매 등록 요청 완료' : '중고 판매 등록 요청'}
      </button>
    </div>
  );
}
