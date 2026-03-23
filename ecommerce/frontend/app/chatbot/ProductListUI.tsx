'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../authcontext';
import SharedProductListUI, {
  type ProductListUIClassNames,
  type ProductOption,
  type UiProduct,
} from './shared/ProductListUI';
import styles from './productlist.module.css';

const API_BASE = process.env.NEXT_PUBLIC_API_URL;
export const ECOMMERCE_SHARED_WIDGET_CAPABILITIES = 'full' as const;

type ProductListUIProps = {
  products?: UiProduct[];
  message?: string;
};

export default function ProductListUI({ products = [], message }: ProductListUIProps) {
  const router = useRouter();
  const { isLoggedIn } = useAuth();

  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<ProductOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] = useState<Record<number, number | null>>({});
  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] = useState<Record<number, string>>({});

  const requireLogin = (callback: () => void) => {
    if (isLoggedIn === null) return;
    if (!isLoggedIn) {
      alert('로그인이 필요한 기능입니다.');
      return;
    }
    callback();
  };

  const openSizeModal = (productId: number) => {
    requireLogin(async () => {
      setSizeModalOpenFor(productId);
      setOptions([]);
      setOptionsLoading(true);

      try {
        const res = await fetch(`${API_BASE}/products/new/${productId}/options`, {
          credentials: 'include',
        });

        if (!res.ok) throw new Error();

        const data: ProductOption[] = await res.json();
        const filtered = data.filter((o) => o.is_active && o.quantity > 0);
        setOptions(filtered);
      } catch {
        alert('사이즈 정보를 불러오지 못했습니다.');
        setSizeModalOpenFor(null);
      } finally {
        setOptionsLoading(false);
      }
    });
  };

  const closeSizeModal = () => {
    setSizeModalOpenFor(null);
    setOptions([]);
  };

  const selectOption = (productId: number, option: ProductOption) => {
    setSelectedOptionIdByProduct((prev) => ({
      ...prev,
      [productId]: option.id,
    }));
    setSelectedSizeLabelByProduct((prev) => ({
      ...prev,
      [productId]: option.size_name || '선택됨',
    }));
    closeSizeModal();
  };

  const addToCart = async (productId: number, goPayment: boolean) => {
    requireLogin(async () => {
      const optionId = selectedOptionIdByProduct[productId];

      if (!optionId) {
        openSizeModal(productId);
        return;
      }

      try {
        const userRes = await fetch(`${API_BASE}/users/me`, { credentials: 'include' });
        const userData = await userRes.json();
        const userId = userData.id;

        const res = await fetch(`${API_BASE}/carts/${userId}/items`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product_option_type: 'new',
            product_option_id: optionId,
            quantity: 1,
          }),
        });

        if (!res.ok) {
          alert('장바구니 추가 실패');
          return;
        }

        if (goPayment) {
          router.push('/payment');
        } else {
          alert('장바구니에 담았습니다.');
        }
      } catch {
        alert('요청 실패');
      }
    });
  };

  return (
    <SharedProductListUI
      products={products}
      message={message}
      sizeModalOpenFor={sizeModalOpenFor}
      options={options}
      optionsLoading={optionsLoading}
      selectedSizeLabelByProduct={selectedSizeLabelByProduct}
      onOpenSizeModal={openSizeModal}
      onCloseSizeModal={closeSizeModal}
      onSelectOption={selectOption}
      onAddToCart={addToCart}
      resolveImageSrc={(product) => product.image_url || `/products/${product.id}.jpg`}
      classNames={styles as ProductListUIClassNames}
    />
  );
}

export type { UiProduct };
