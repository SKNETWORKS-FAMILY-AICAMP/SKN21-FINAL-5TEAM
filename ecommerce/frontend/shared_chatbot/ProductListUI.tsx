import React from 'react';

export type UiProduct = {
  id: number;
  name: string;
  price: number;
  category?: string;
  color?: string;
  season?: string;
  image_url?: string;
};

export type ProductOption = {
  id: number;
  product_id: number;
  size_name: string | null;
  color: string | null;
  quantity: number;
  is_active: boolean;
};

export type ProductListUIClassNames = Partial<{
  container: string;
  message: string;
  productList: string;
  productCard: string;
  productImageWrap: string;
  productInfo: string;
  productName: string;
  productMeta: string;
  productPrice: string;
  actionRow: string;
  btn: string;
  primary: string;
  modalOverlay: string;
  modalTitle: string;
  sizeGrid: string;
  sizeBtn: string;
  closeModalBtn: string;
}>;

type ProductListUIProps = {
  products?: UiProduct[];
  message?: string;
  purchaseEnabled?: boolean;
  sizeModalOpenFor?: number | null;
  options?: ProductOption[];
  optionsLoading?: boolean;
  selectedSizeLabelByProduct?: Record<number, string>;
  onOpenSizeModal?: (productId: number) => void;
  onCloseSizeModal?: () => void;
  onSelectOption?: (productId: number, option: ProductOption) => void;
  onAddToCart?: (productId: number, goPayment: boolean) => void;
  resolveImageSrc?: (product: UiProduct) => string | undefined;
  classNames?: ProductListUIClassNames;
};

export default function ProductListUI({
  products = [],
  message,
  purchaseEnabled = true,
  sizeModalOpenFor = null,
  options = [],
  optionsLoading = false,
  selectedSizeLabelByProduct = {},
  onOpenSizeModal,
  onCloseSizeModal,
  onSelectOption,
  onAddToCart,
  resolveImageSrc,
  classNames,
}: ProductListUIProps) {
  const uniqueSizes = React.useMemo(() => {
    const map = new Map<string, ProductOption>();
    options.forEach((option) => {
      const key = option.size_name ?? 'FREE';
      if (!map.has(key)) {
        map.set(key, option);
      }
    });
    return Array.from(map.entries()).map(([size, opt]) => ({ size, opt }));
  }, [options]);

  return (
    <div className={classNames?.container}>
      {message && <div className={classNames?.message}>{message}</div>}
      <div className={classNames?.productList}>
        {products.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];
          const imgUrl = resolveImageSrc?.(product) ?? product.image_url;

          return (
            <div key={product.id} className={classNames?.productCard}>
              <div className={classNames?.productImageWrap}>
                {imgUrl ? (
                  <img
                    src={imgUrl}
                    alt={product.name}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : null}
              </div>

              <div className={classNames?.productInfo}>
                <div>
                  <h4 className={classNames?.productName}>{product.name}</h4>
                  <p className={classNames?.productMeta}>
                    {product.category && `${product.category} | `}
                    {product.color && `${product.color} `}
                  </p>
                  <p className={classNames?.productPrice}>{Math.round(product.price ?? 0).toLocaleString()}원</p>
                </div>

                {purchaseEnabled ? (
                  <div className={classNames?.actionRow}>
                    <button
                      type="button"
                      className={classNames?.btn}
                      onClick={() => onOpenSizeModal?.(product.id)}
                    >
                      {selectedLabel || '사이즈 선택'}
                    </button>
                    <button
                      type="button"
                      className={classNames?.btn}
                      onClick={() => onAddToCart?.(product.id, false)}
                    >
                      장바구니
                    </button>
                    <button
                      type="button"
                      className={[classNames?.btn, classNames?.primary].filter(Boolean).join(' ')}
                      onClick={() => onAddToCart?.(product.id, true)}
                    >
                      바로 구매
                    </button>
                  </div>
                ) : null}
              </div>

              {purchaseEnabled && sizeModalOpenFor === product.id && (
                <div className={classNames?.modalOverlay} onClick={() => onCloseSizeModal?.()}>
                  <button
                    type="button"
                    className={classNames?.closeModalBtn}
                    onClick={() => onCloseSizeModal?.()}
                  >
                    ✕
                  </button>
                  <div
                    style={{ width: '100%', maxWidth: '240px' }}
                    onClick={(event) => event.stopPropagation()}
                  >
                    <h4 className={classNames?.modalTitle}>사이즈 선택</h4>
                    {optionsLoading ? (
                      <p style={{ fontSize: '12px' }}>불러오는 중...</p>
                    ) : uniqueSizes.length === 0 ? (
                      <p style={{ fontSize: '12px', color: '#666' }}>선택 가능한 사이즈가 없습니다.</p>
                    ) : (
                      <div className={classNames?.sizeGrid}>
                        {uniqueSizes.map(({ size, opt }) => (
                          <button
                            key={size}
                            type="button"
                            className={classNames?.sizeBtn}
                            onClick={() => onSelectOption?.(product.id, opt)}
                          >
                            {size}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
