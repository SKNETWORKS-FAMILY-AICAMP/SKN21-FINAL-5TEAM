import React from 'react';
import productListStyles from './productlist.module.css';

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
  const mergedClassNames = {
    container: classNames?.container ?? productListStyles.container,
    message: classNames?.message ?? productListStyles.message,
    productList: classNames?.productList ?? productListStyles.productList,
    productCard: classNames?.productCard ?? productListStyles.productCard,
    productImageWrap: classNames?.productImageWrap ?? productListStyles.productImageWrap,
    productInfo: classNames?.productInfo ?? productListStyles.productInfo,
    productName: classNames?.productName ?? productListStyles.productName,
    productMeta: classNames?.productMeta ?? productListStyles.productMeta,
    productPrice: classNames?.productPrice ?? productListStyles.productPrice,
    actionRow: classNames?.actionRow ?? productListStyles.actionRow,
    btn: classNames?.btn ?? productListStyles.btn,
    primary: classNames?.primary ?? productListStyles.primary,
    modalOverlay: classNames?.modalOverlay ?? productListStyles.modalOverlay,
    modalTitle: classNames?.modalTitle ?? productListStyles.modalTitle,
    sizeGrid: classNames?.sizeGrid ?? productListStyles.sizeGrid,
    sizeBtn: classNames?.sizeBtn ?? productListStyles.sizeBtn,
    closeModalBtn: classNames?.closeModalBtn ?? productListStyles.closeModalBtn,
  } as const;

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
    <div className={mergedClassNames.container}>
      {message && <div className={mergedClassNames.message}>{message}</div>}
      <div className={mergedClassNames.productList}>
        {products.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];
          const imgUrl = resolveImageSrc?.(product) ?? product.image_url;

          return (
            <div key={product.id} className={mergedClassNames.productCard}>
              <div className={mergedClassNames.productImageWrap}>
                {imgUrl ? (
                  <img
                    src={imgUrl}
                    alt={product.name}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : null}
              </div>

              <div className={mergedClassNames.productInfo}>
                <div>
                  <h4 className={mergedClassNames.productName}>{product.name}</h4>
                  <p className={mergedClassNames.productMeta}>
                    {product.category && `${product.category} | `}
                    {product.color && `${product.color} `}
                  </p>
                  <p className={mergedClassNames.productPrice}>{Math.round(product.price ?? 0).toLocaleString()}원</p>
                </div>

                {purchaseEnabled ? (
                  <div className={mergedClassNames.actionRow}>
                    <button
                      type="button"
                      className={mergedClassNames.btn}
                      onClick={() => onOpenSizeModal?.(product.id)}
                    >
                      {selectedLabel || '사이즈 선택'}
                    </button>
                    <button
                      type="button"
                      className={mergedClassNames.btn}
                      onClick={() => onAddToCart?.(product.id, false)}
                    >
                      장바구니
                    </button>
                    <button
                      type="button"
                      className={[mergedClassNames.btn, mergedClassNames.primary].filter(Boolean).join(' ')}
                      onClick={() => onAddToCart?.(product.id, true)}
                    >
                      바로 구매
                    </button>
                  </div>
                ) : null}
              </div>

              {purchaseEnabled && sizeModalOpenFor === product.id && (
                <div className={mergedClassNames.modalOverlay} onClick={() => onCloseSizeModal?.()}>
                  <button
                    type="button"
                    className={mergedClassNames.closeModalBtn}
                    onClick={() => onCloseSizeModal?.()}
                  >
                    ✕
                  </button>
                  <div
                    style={{ width: '100%', maxWidth: '240px' }}
                    onClick={(event) => event.stopPropagation()}
                  >
                    <h4 className={mergedClassNames.modalTitle}>사이즈 선택</h4>
                    {optionsLoading ? (
                      <p style={{ fontSize: '12px' }}>불러오는 중...</p>
                    ) : uniqueSizes.length === 0 ? (
                      <p style={{ fontSize: '12px', color: '#666' }}>선택 가능한 사이즈가 없습니다.</p>
                    ) : (
                      <div className={mergedClassNames.sizeGrid}>
                        {uniqueSizes.map(({ size, opt }) => (
                          <button
                            key={size}
                            type="button"
                            className={mergedClassNames.sizeBtn}
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
